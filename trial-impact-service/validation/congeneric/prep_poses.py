"""Stage A of the congeneric ranking experiment (Experiment A; run in the trialsim
conda env, PYTHONPATH=service root). For one target (default tyk2) it:

  1. downloads the FIXED reference structure (structure_pdb_id in ligands.json) once,
     builds one receptor (ATOM-only PDB + rigid PDBQT) shared by every ligand, and boxes
     on the co-crystal ligand's pocket -- so all analogs are docked into the *identical*
     receptor/pocket (the design that removes the cross-target size/pocket confound),
  2. for each congeneric ligand: embed the SMILES, dock into the shared box (single top
     pose, pipeline seed) and persist the pose SDF + a copy of receptor_atoms.pdb + a
     meta.json, exactly the per-ligand layout validation/score_mmgbsa.score_one consumes.

Writes validation/congeneric/work/<target>/<ligand_id>/. Optional argv = target name.

    PYTHONPATH=. micromamba run -n trialsim python validation/congeneric/prep_poses.py tyk2
"""
import json
import os
import shutil
import sys

from app import simulation as sim
from validation.pose_fidelity.selfdock import _dock_box

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "work")

# Non-ligand HET codes (ions, buffers, cryoprotectants) that must not be mistaken for
# the co-crystal ligand when centering the docking box.
_EXCLUDE = {"CL", "NA", "K", "MG", "CA", "ZN", "SO4", "PO4", "GOL", "EDO", "ACT",
            "HOH", "DMS", "MES", "TRS", "PEG", "BME", "IOD", "BR", "FMT", "NO3"}


def _primary_ligand_block(pdb_path: str) -> str:
    """HETATM block of the largest non-ion/-buffer ligand (first model, primary altloc)."""
    groups: dict[tuple[str, str, str], list[str]] = {}
    with open(pdb_path) as fh:
        for line in fh:
            rec = line[:6].strip()
            if rec == "ENDMDL":
                break
            if rec != "HETATM":
                continue
            resname = line[17:20].strip()
            if resname in _EXCLUDE:
                continue
            if line[16] not in (" ", "A"):  # skip alt-conf B+
                continue
            key = (resname, line[21], line[22:27])
            groups.setdefault(key, []).append(line)
    if not groups:
        raise RuntimeError(f"no drug-like HETATM ligand in {os.path.basename(pdb_path)}")
    best = max(groups.values(), key=len)
    return "".join(best)


def _receptor_atoms_pdb(pdb_path: str, out: str) -> None:
    with open(pdb_path) as src, open(out, "w") as dst:
        for line in src:
            if line.startswith("ENDMDL"):
                break
            if line.startswith(("ATOM", "TER")):
                dst.write(line)
        dst.write("END\n")


def prep_target(target: str) -> None:
    manifest = json.load(open(os.path.join(HERE, target, "ligands.json")))
    pdb_id = manifest["structure_pdb_id"]
    shared = os.path.join(WORK, target, "_shared")
    os.makedirs(shared, exist_ok=True)

    pdb_path, fmt = sim._fetch_experimental_pdb(pdb_id, shared)
    receptor_atoms = os.path.join(shared, "receptor_atoms.pdb")
    _receptor_atoms_pdb(pdb_path, receptor_atoms)
    receptor_pdbqt = sim.prepare_receptor_pdbqt(pdb_path, shared)  # rigid, ATOM-only
    box = _dock_box(_primary_ligand_block(pdb_path), pad=7.0, cap=22.0)
    print(f"{target}: structure {pdb_id} ({fmt}); box size "
          f"{[round(x, 1) for x in box[1]]}", flush=True)

    from meeko import PDBQTMolecule, RDKitMolCreate
    from rdkit import Chem
    from vina import Vina

    for lig in manifest["ligands"]:
        lig_id = lig["id"]
        d = os.path.join(WORK, target, lig_id)
        os.makedirs(d, exist_ok=True)
        try:
            mol = sim.embed_ligand(lig["smiles"])
            ligand_pdbqt = sim.prepare_ligand_pdbqt(mol, d)
            v = Vina(sf_name="vina", cpu=os.cpu_count() or 1, seed=sim._VINA_SEED)
            v.set_receptor(receptor_pdbqt)
            v.set_ligand_from_file(ligand_pdbqt)
            v.compute_vina_maps(center=box[0], box_size=box[1])
            v.dock(exhaustiveness=8, n_poses=5)
            vina_dg = float(v.energies(n_poses=1)[0][0])
            pose_pdbqt = os.path.join(d, "ligand_pose.pdbqt")
            v.write_poses(pose_pdbqt, n_poses=1, overwrite=True)
            pmol = PDBQTMolecule.from_file(pose_pdbqt, skip_typing=True)
            pose = RDKitMolCreate.from_pdbqt_mol(pmol)[0]
            if pose is None:
                raise RuntimeError("Meeko could not reconstruct the docked ligand")
            w = Chem.SDWriter(os.path.join(d, "ligand_pose.sdf"))
            w.write(pose)
            w.close()
            shutil.copyfile(receptor_atoms, os.path.join(d, "receptor_atoms.pdb"))
            meta = {
                "target": target, "drug": lig_id, "mode": "congeneric-fixed-receptor",
                "pdb_id": pdb_id, "vina_dg": vina_dg,
                "smiles": lig["smiles"], "heavy_atoms": lig["heavy_atoms"],
                "paffinity": lig["paffinity"], "affinity_type": lig["affinity_type"],
                "n_lig_atoms": pose.GetNumAtoms(),
            }
            json.dump(meta, open(os.path.join(d, "meta.json"), "w"), indent=2)
            print(json.dumps({"id": lig_id, "vina_dg": round(vina_dg, 2),
                              "paffinity": lig["paffinity"]}), flush=True)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            print(f"FAILED {target} {lig_id}: {type(exc).__name__}: {exc}", flush=True)


def main() -> int:
    os.makedirs(WORK, exist_ok=True)
    targets = sys.argv[1:] or ["tyk2"]
    for t in targets:
        print(f"=== prep congeneric {t} ===", flush=True)
        prep_target(t)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
