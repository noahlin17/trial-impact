"""Stage 1 of pose fidelity (Experiment C): self-dock the native ligand of each
committed co-crystal back into its own crystal receptor and measure how close the top
docked pose lands to the deposited crystallographic pose.

For each complex in ``complexes.json`` (run in the trialsim conda env, PYTHONPATH=service
root):

  1. download the crystal (RCSB), split protein (ATOM) receptor from the native ligand
     (HETATM of the manifest's HET code),
  2. build a REFERENCE ligand = crystal heavy-atom coordinates with bond orders assigned
     from the ligand's ideal SMILES (RCSB chemcomp), so RMSD is chemically correct,
  3. redock a FRESH RDKit conformer of that ligand into the receptor across the pipeline's
     seed set, boxing on the crystal-ligand centroid (pocket known -> focused box), and
  4. for each seed, symmetry-corrected heavy-atom RMSD of the top pose to the reference,
     computed WITHOUT re-superposition (docking runs in the crystal frame).

Writes validation/pose_fidelity/work/<pdb>/ and a combined work/selfdock_raw.json.
Optional argv restricts to given PDB IDs.

    PYTHONPATH=. micromamba run -n trialsim python validation/pose_fidelity/selfdock.py 4GIH
"""
import json
import os
import sys
import urllib.request

from app import simulation as sim

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "work")
RCSB = "https://data.rcsb.org/rest/v1/core"


def _ligand_smiles(het: str) -> str:
    """Ideal SMILES for a HET code from the RCSB chemical-component API."""
    url = f"{RCSB}/chemcomp/{het.upper()}"
    with urllib.request.urlopen(url, timeout=60) as fh:  # noqa: S310 (pinned host)
        d = json.loads(fh.read().decode())
    desc = d.get("rcsb_chem_comp_descriptor", {})
    smi = desc.get("SMILES_stereo") or desc.get("SMILES")
    if not smi:
        raise RuntimeError(f"no SMILES for HET {het}")
    return smi


def _split_receptor_and_ligand(pdb_path: str, het: str, rec_out: str) -> str:
    """Write protein ATOM records to ``rec_out``; return the ligand HETATM block.

    Takes the first copy of the HET code (first chain + primary altloc) from the first
    model only, so a multi-copy or alt-conf ligand yields one clean reference.
    """
    het = het.upper()
    lig_lines: list[str] = []
    lig_key: tuple[str, str] | None = None
    with open(pdb_path) as src, open(rec_out, "w") as dst:
        for line in src:
            rec = line[:6].strip()
            if rec == "ENDMDL":
                break
            if rec == "ATOM":
                dst.write(line)
            elif rec == "HETATM" and line[17:20].strip() == het:
                altloc = line[16]
                if altloc not in (" ", "A"):
                    continue
                key = (line[21], line[22:27])  # chain, resSeq(+icode)
                if lig_key is None:
                    lig_key = key
                if key == lig_key:
                    lig_lines.append(line)
        dst.write("END\n")
    if not lig_lines:
        raise RuntimeError(f"no HETATM {het} found in {os.path.basename(pdb_path)}")
    return "".join(lig_lines)


def _reference_mol(lig_block: str, smiles: str):
    """Crystal-coordinate ligand with correct bond orders (heavy atoms only)."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    raw = Chem.MolFromPDBBlock(lig_block, sanitize=False, removeHs=True)
    if raw is None:
        raise RuntimeError("RDKit could not read the crystal ligand block")
    template = Chem.MolFromSmiles(smiles)
    if template is None:
        raise RuntimeError(f"unparseable ligand SMILES: {smiles}")
    template = Chem.RemoveHs(template)
    ref = AllChem.AssignBondOrdersFromTemplate(template, raw)
    return Chem.RemoveHs(ref)


def _dock_box(lig_block: str, pad: float = 5.0, cap: float = 20.0):
    """Focused redocking box on the crystal-ligand centroid (pocket is known here).

    Redocking convention: ligand bounding box + ~``pad`` A per side. A permissive box
    lets Vina place a displaced/rotated mode that scores as well but is not the crystal
    pose, so pose fidelity is tested with a tight, pocket-focused box (this matches the
    product's pocket-aware routing, not blind whole-protein docking).
    """
    import numpy as np

    coords = [(float(ln[30:38]), float(ln[38:46]), float(ln[46:54]))
              for ln in lig_block.splitlines()]
    arr = np.array(coords)
    center = arr.mean(axis=0)
    size = np.minimum((arr.max(axis=0) - arr.min(axis=0)) + 2 * pad, cap)
    size = np.maximum(size, 12.0)  # floor so a small ligand still gets a searchable box
    return center.tolist(), size.tolist()


def _rmsd(probe, ref) -> float:
    """Symmetry-corrected heavy-atom RMSD WITHOUT alignment (both in the crystal frame)."""
    from rdkit.Chem import AllChem, rdMolAlign

    p = AllChem.RemoveHs(probe)
    r = AllChem.RemoveHs(ref)
    return float(rdMolAlign.CalcRMS(p, r))


def selfdock_one(pdb_id: str, het: str) -> dict:
    from meeko import PDBQTMolecule, RDKitMolCreate
    from rdkit import Chem
    from vina import Vina

    out_dir = os.path.join(WORK, pdb_id)
    os.makedirs(out_dir, exist_ok=True)
    pdb_path, fmt = sim._fetch_experimental_pdb(pdb_id, out_dir)

    rec_pdb = os.path.join(out_dir, "receptor_atoms.pdb")
    lig_block = _split_receptor_and_ligand(pdb_path, het, rec_pdb)
    smiles = _ligand_smiles(het)
    ref = _reference_mol(lig_block, smiles)

    receptor_pdbqt = sim.prepare_receptor_pdbqt(rec_pdb, out_dir)
    dock_mol = sim.embed_ligand(Chem.MolToSmiles(ref))  # fresh conformer -> honest redock
    ligand_pdbqt = sim.prepare_ligand_pdbqt(dock_mol, out_dir)
    box = _dock_box(lig_block)

    seeds = sim._derive_seeds(sim._VINA_REPLICATES)
    rmsds, top_dg = [], []
    for s in seeds:
        v = Vina(sf_name="vina", cpu=os.cpu_count() or 1, seed=s)
        v.set_receptor(receptor_pdbqt)
        v.set_ligand_from_file(ligand_pdbqt)
        v.compute_vina_maps(center=box[0], box_size=box[1])
        v.dock(exhaustiveness=8, n_poses=5)
        top_dg.append(float(v.energies(n_poses=1)[0][0]))
        pose_pdbqt = os.path.join(out_dir, f"pose_seed{s}.pdbqt")
        v.write_poses(pose_pdbqt, n_poses=1, overwrite=True)
        pmol = PDBQTMolecule.from_file(pose_pdbqt, skip_typing=True)
        docked = RDKitMolCreate.from_pdbqt_mol(pmol)[0]
        if docked is None:
            raise RuntimeError(f"Meeko could not reconstruct pose (seed {s})")
        rmsds.append(round(_rmsd(docked, ref), 3))

    import statistics
    best = min(rmsds)
    result = {
        "pdb_id": pdb_id, "het": het, "structure_format": fmt,
        "n_ref_heavy": ref.GetNumHeavyAtoms(), "seeds": seeds,
        "rmsd_per_seed": rmsds, "rmsd_top": rmsds[0], "rmsd_best": best,
        "rmsd_median": round(statistics.median(rmsds), 3),
        "rmsd_seed_spread": round(max(rmsds) - min(rmsds), 3),
        "dg_per_seed": [round(x, 3) for x in top_dg],
        "success_2A": bool(best < 2.0),
    }
    json.dump(result, open(os.path.join(out_dir, "result.json"), "w"), indent=2)
    return result


def main() -> int:
    os.makedirs(WORK, exist_ok=True)
    manifest = json.load(open(os.path.join(HERE, "complexes.json")))["complexes"]
    if len(sys.argv) > 1:
        want = {a.upper() for a in sys.argv[1:]}
        manifest = [c for c in manifest if c["pdb_id"].upper() in want]
    out = []
    for c in manifest:
        pdb_id, het = c["pdb_id"], c["ligand_het_code"]
        print(f"=== self-dock {pdb_id} ({het}) ===", flush=True)
        try:
            row = selfdock_one(pdb_id, het)
            print(json.dumps({k: row[k] for k in
                              ("rmsd_top", "rmsd_best", "rmsd_seed_spread", "success_2A")}),
                  flush=True)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            row = {"pdb_id": pdb_id, "het": het, "error": f"{type(exc).__name__}: {exc}"}
            print(f"FAILED {pdb_id}: {row['error']}", flush=True)
        out.append(row)
    json.dump(out, open(os.path.join(WORK, "selfdock_raw.json"), "w"), indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
