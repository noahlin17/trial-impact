#!/usr/bin/env python3
"""Measure how much of the receptor the blind docking box actually contains.

`compute_docking_box` centers a box on the receptor centroid and sizes it
`min(extent + 8 Å, 40 Å)`. The 40 Å cap keeps the search volume tractable for
Vina — but when it binds, the box stops covering the receptor, and the code says
nothing about it. This script makes that visible: it calls the *committed*
pipeline functions (no re-implementation) and reports the fraction of receptor
atoms that fall inside the box Vina would have searched.

    python verify_docking_box.py                # both published runs
    python verify_docking_box.py --target KRAS  # one target

The two published results measure as:

    KRAS  (7VVB, experimental)    ~80% of receptor atoms inside the box
    CFTR  (AF-P13569-F1, predicted)  ~19%

CFTR is a 1480-residue membrane protein and ivacaftor binds at the TM1/TM6
interface, not the centroid — so its ΔG is a dock into an arbitrary central
slab, not a pocket. See "Docking box" under Limitations in README.md.

Note the box is computed over ATOM *and* HETATM records while the receptor that
is actually docked is ATOM-only (`prepare_receptor_pdbqt` drops waters and
heteroatoms), so the box is centered on a slightly different atom set than the
one it searches. This script reports coverage over the ATOM-only set — the atoms
that are really there during docking.
"""

from __future__ import annotations

import argparse
import tempfile

from app.simulation import compute_docking_box, fetch_structure, resolve_uniprot

# The two targets behind the published results (see results/README.md).
TARGETS = {
    "KRAS": "sotorasib",
    "CFTR": "ivacaftor",
}


def receptor_atoms(pdb_path: str) -> list[tuple[float, float, float]]:
    """The ATOM records — i.e. exactly what `prepare_receptor_pdbqt` keeps."""
    coords = []
    with open(pdb_path) as fh:
        for line in fh:
            if line.startswith("ATOM"):
                coords.append(
                    (float(line[30:38]), float(line[38:46]), float(line[46:54]))
                )
            elif line.startswith("ENDMDL"):
                break
    return coords


def measure(target: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory() as workdir:
        uniprot = resolve_uniprot(target)
        pdb_path, prov = fetch_structure(uniprot, workdir)
        center, size = compute_docking_box(pdb_path)

        atoms = receptor_atoms(pdb_path)
        lo = [c - s / 2 for c, s in zip(center, size, strict=False)]
        hi = [c + s / 2 for c, s in zip(center, size, strict=False)]
        inside = sum(
            1
            for a in atoms
            if all(lo[i] <= a[i] <= hi[i] for i in range(3))
        )

        xs, ys, zs = zip(*atoms, strict=False)
        extent = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))

        return {
            "target": target,
            "structure": prov.get("pdb_id") or prov.get("source"),
            "atoms": len(atoms),
            "inside": inside,
            "coverage_pct": 100.0 * inside / len(atoms) if atoms else 0.0,
            "extent": extent,
            "box_size": size,
            "capped": any(s >= 40.0 for s in size),
        }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--target", choices=sorted(TARGETS), help="default: all")
    args = ap.parse_args()

    targets = [args.target] if args.target else sorted(TARGETS)
    for t in targets:
        r = measure(t)
        ex = r["extent"]
        print(f"\n{r['target']}  ({TARGETS[t]})  structure={r['structure']}")
        print(f"  receptor extent   {ex[0]:.0f} x {ex[1]:.0f} x {ex[2]:.0f} Å")
        print(f"  docking box       {[round(s, 1) for s in r['box_size']]} Å"
              f"{'   <- 40 Å cap is binding' if r['capped'] else ''}")
        print(f"  atoms in the box  {r['inside']}/{r['atoms']}"
              f"  =  {r['coverage_pct']:.1f}% of the receptor")
    print()


if __name__ == "__main__":
    main()
