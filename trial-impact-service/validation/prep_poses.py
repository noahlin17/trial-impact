"""Stage A of the scoring validation (run in the trialsim conda env, PYTHONPATH set
to the service root): for each anchor in anchors.json, route + dock through the
production pipeline and persist the two artifacts an MM-GBSA rescorer needs -- a clean
receptor-protein PDB and the top docked pose as an SDF with correct bond orders/Hs
(Meeko round-trip). The pose we rescore is therefore the SAME pose Vina scored.

Writes validation/work/<target>_<drug>/. Optional argv restricts to "TARGET:DRUG".

    PYTHONPATH=. micromamba run -n trialsim python validation/prep_poses.py
"""
import json
import os
import sys

from app import simulation as sim
from app.binding_site import select_binding_site

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "work")


def load_anchors() -> list[tuple[str, str]]:
    data = json.load(open(os.path.join(HERE, "anchors.json")))
    return [(a["target"], a["drug"]) for a in data["anchors"]]


def prep_one(target: str, drug: str) -> dict:
    out_dir = os.path.join(WORK, f"{target}_{drug}")
    os.makedirs(out_dir, exist_ok=True)

    accession = sim.resolve_uniprot(target, None)
    smiles = sim.fetch_ligand_smiles(drug)
    mol = sim.embed_ligand(smiles)
    site = select_binding_site(
        target=target, uniprot=accession, smiles=smiles,
        mol=mol, covalent=sim.detect_covalent(mol), workdir=out_dir,
    )
    meta = {"target": target, "drug": drug, "uniprot": accession, "smiles": smiles,
            "mode": site.mode, "pdb_id": site.structure_prov.get("pdb_id"),
            "center": site.center, "size": site.size}

    receptor_pdb = os.path.join(out_dir, "receptor_atoms.pdb")
    with open(site.pdb_path) as src, open(receptor_pdb, "w") as dst:
        for line in src:
            if line.startswith(("ATOM", "TER")):
                dst.write(line)
        dst.write("END\n")

    receptor_pdbqt = sim.prepare_receptor_pdbqt(site.pdb_path, out_dir)
    ligand_pdbqt = site.ligand_pdbqt or sim.prepare_ligand_pdbqt(mol, out_dir)

    from vina import Vina
    v = Vina(sf_name="vina", cpu=os.cpu_count() or 1, seed=sim._VINA_SEED)
    v.set_receptor(receptor_pdbqt)
    v.set_ligand_from_file(ligand_pdbqt)
    v.compute_vina_maps(center=site.center, box_size=site.size)
    v.dock(exhaustiveness=8, n_poses=5)
    meta["vina_dg"] = float(v.energies(n_poses=1)[0][0])
    pose_pdbqt = os.path.join(out_dir, "ligand_pose.pdbqt")
    v.write_poses(pose_pdbqt, n_poses=1, overwrite=True)

    from meeko import PDBQTMolecule, RDKitMolCreate
    pmol = PDBQTMolecule.from_file(pose_pdbqt, skip_typing=True)
    lig = RDKitMolCreate.from_pdbqt_mol(pmol)[0]
    if lig is None:
        raise RuntimeError("Meeko could not reconstruct the docked ligand")
    from rdkit import Chem
    writer = Chem.SDWriter(os.path.join(out_dir, "ligand_pose.sdf"))
    writer.write(lig)
    writer.close()
    meta["n_lig_atoms"] = lig.GetNumAtoms()
    json.dump(meta, open(os.path.join(out_dir, "meta.json"), "w"), indent=2)
    return meta


def main() -> int:
    os.makedirs(WORK, exist_ok=True)
    picks = load_anchors()
    if len(sys.argv) > 1:
        want = {a.upper() for a in sys.argv[1:]}
        picks = [(t, d) for (t, d) in picks if f"{t}:{d}".upper() in want]
    for target, drug in picks:
        print(f"=== prep {target} x {drug} ===", flush=True)
        try:
            meta = prep_one(target, drug)
            print(json.dumps({k: meta[k] for k in
                              ("mode", "pdb_id", "vina_dg", "n_lig_atoms")}), flush=True)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"FAILED {target} x {drug}: {type(exc).__name__}: {exc}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
