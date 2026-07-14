"""Stage B of the scoring validation (run in the mmgbsa conda env): single-snapshot
MM-GBSA rescore of each prepped anchor. For each validation/work/<t>_<d>/ it

  1. PDBFixer-cleans the receptor (add missing heavy atoms + Hs at pH 7; NO loop
     modelling),
  2. parametrises protein (ff14SB) + docked ligand (GAFF-2.11 / AM1-BCC) with an
     OpenMM implicit-solvent (OBC2) system via openmmforcefields,
  3. minimises the ligand pose in a RIGID receptor (protein frozen) to relieve the
     docking clashes an all-atom force field sees, then reads single-point energies at
     that geometry and reports

        dG_MMGBSA = E_complex - E_receptor - E_ligand      (kcal/mol, no entropy).

Because the frozen receptor coordinates are identical in the complex and receptor-only
single points, the receptor-internal energy cancels, leaving interaction + desolvation
+ ligand strain -- the terms Vina's size-dominated score misses. This is the CHEAP end
of MM-GBSA (one pose, rigid receptor, no -TdS): a screening estimate, not a calibrated
binding free energy. Writes validation/work/scores_raw.json.
"""
import glob
import json
import os

from openff.toolkit import Molecule
from openmm import LocalEnergyMinimizer, app, unit
from openmmforcefields.generators import SystemGenerator

HERE = os.path.dirname(__file__)
WORK = os.path.join(HERE, "work")
KCAL = unit.kilocalorie_per_mole


def _fix_receptor(pdb_in: str, pdb_out: str) -> app.PDBFile:
    from pdbfixer import PDBFixer
    fixer = PDBFixer(filename=pdb_in)
    fixer.findMissingResidues()
    fixer.missingResidues = {}
    fixer.findNonstandardResidues()
    fixer.replaceNonstandardResidues()
    fixer.removeHeterogens(keepWater=False)
    fixer.findMissingAtoms()
    fixer.addMissingAtoms()
    fixer.addMissingHydrogens(7.0)
    with open(pdb_out, "w") as fh:
        app.PDBFile.writeFile(fixer.topology, fixer.positions, fh)
    return app.PDBFile(pdb_out)


def _context(system, topology):
    from openmm import LangevinIntegrator, Platform
    integ = LangevinIntegrator(300 * unit.kelvin, 1 / unit.picosecond,
                               0.002 * unit.picoseconds)
    return app.Simulation(topology, system, integ,
                          Platform.getPlatformByName("CPU")).context


def _energy_at(system, topology, positions) -> float:
    ctx = _context(system, topology)
    ctx.setPositions(positions)
    return ctx.getState(getEnergy=True).getPotentialEnergy().value_in_unit(KCAL)


def score_one(d: str) -> dict:
    meta = json.load(open(os.path.join(d, "meta.json")))
    rec = _fix_receptor(os.path.join(d, "receptor_atoms.pdb"),
                        os.path.join(d, "receptor_fixed.pdb"))
    lig = Molecule.from_file(os.path.join(d, "ligand_pose.sdf"))

    gen = SystemGenerator(
        forcefields=["amber/ff14SB.xml", "implicit/obc2.xml"],
        small_molecule_forcefield="gaff-2.11",
        molecules=[lig],
        forcefield_kwargs={"constraints": None, "rigidWater": False},
        nonperiodic_forcefield_kwargs={"nonbondedMethod": app.NoCutoff},
    )

    lig_top = lig.to_topology().to_openmm()
    lig_pos = lig.conformers[0].to_openmm()
    n_rec = rec.topology.getNumAtoms()

    model = app.Modeller(rec.topology, rec.positions)
    model.add(lig_top, lig_pos)

    sys_min = gen.create_system(model.topology)
    for i in range(n_rec):
        sys_min.setParticleMass(i, 0.0)          # freeze receptor
    ctx = _context(sys_min, model.topology)
    ctx.setPositions(model.getPositions())
    LocalEnergyMinimizer.minimize(ctx, tolerance=10.0, maxIterations=1000)
    min_pos = ctx.getState(getPositions=True).getPositions(asNumpy=True)

    e_cpx = _energy_at(gen.create_system(model.topology), model.topology, min_pos)
    e_rec = _energy_at(gen.create_system(rec.topology), rec.topology, min_pos[:n_rec])
    e_lig = _energy_at(gen.create_system(lig_top), lig_top, min_pos[n_rec:])
    dg = e_cpx - e_rec - e_lig
    return {"target": meta["target"], "drug": meta["drug"], "mode": meta["mode"],
            "pdb_id": meta.get("pdb_id"), "vina_dg": meta.get("vina_dg"),
            "e_complex": round(e_cpx, 2), "e_receptor": round(e_rec, 2),
            "e_ligand": round(e_lig, 2), "dg_mmgbsa": round(dg, 3)}


def main() -> int:
    out = []
    for meta_path in sorted(glob.glob(os.path.join(WORK, "*", "meta.json"))):
        d = os.path.dirname(meta_path)
        try:
            row = score_one(d)
        except Exception as exc:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            row = {"dir": os.path.basename(d), "error": f"{type(exc).__name__}: {exc}"}
        out.append(row)
        print(json.dumps(row), flush=True)
    json.dump(out, open(os.path.join(WORK, "scores_raw.json"), "w"), indent=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
