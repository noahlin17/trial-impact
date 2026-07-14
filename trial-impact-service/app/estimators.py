"""Estimators: interchangeable implementations behind one interface.

The docking + PK/PD pipeline in :mod:`app.simulation` is *one* way to turn a
``(target, drug, tissue, dose)`` tuple into a :class:`~app.simulation.SimResult`.
It is deliberately not the architecture. The physics has no moat — a blind,
box-capped Vina score is a directional signal, not ground truth — so the unit the
system is built around is the **estimator interface**, and the product is the
*comparison* between estimators run head-to-head on the same trials, not any single
model's number.

An :class:`Estimator` is anything that implements ``run(...) -> SimResult`` and carries
a stable ``id`` (``name@version``). Every result it produces is stamped with that id
(``SimResult.estimator``) so a corpus spanning multiple models stays interpretable and a
head-to-head is possible at all. Register a new estimator in :data:`REGISTRY` and it is
immediately runnable from the CLI (``python -m app.simulation --estimator <id>``) and
selectable per-event by the service.

Two implementations ship today:

* :class:`VinaDockingEstimator` — the real structure-based docking pipeline.
* :class:`LigandEfficiencyBaseline` — a structure-free control (see its docstring). It
  exists so the head-to-head has a floor: docking has to *beat the cheap baseline* to
  have earned its cost, and a model that cannot is not adding information.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from .simulation import (
    VINA_ESTIMATOR_ID,
    SimResult,
    fetch_ligand_smiles,
    kd_from_dg,
    ligand_descriptors,
    resolve_fu,
    run_pkpd,
    run_simulation,
)


@runtime_checkable
class Estimator(Protocol):
    """Turns a trial's ``(target, drug, tissue, dose)`` into a :class:`SimResult`.

    Implementations must:

    * expose a stable ``id`` of the form ``name@version`` — bump the version whenever a
      change would move the numbers, so a stored result always names the exact model
      that produced it;
    * stamp ``result.estimator = self.id`` on every result they return;
    * never raise for a *modelling* failure — surface it on ``result.error`` /
      ``result.warnings`` so a bad run is data, not a crash (mirrors
      :func:`app.simulation.run_simulation`).
    """

    id: str

    def run(
        self,
        *,
        target: str,
        drug: str,
        tissue: str = "plasma",
        dose_mg: float = 100.0,
        uniprot: str | None = None,
        fu: float | None = None,
    ) -> SimResult: ...


class VinaDockingEstimator:
    """The structure-based docking + PK/PD pipeline (:func:`app.simulation.run_simulation`).

    A thin adapter: it delegates to the existing pipeline unchanged and only guarantees
    the result is stamped with this estimator's id. This is the model the baseline
    exists to be compared against.
    """

    id = VINA_ESTIMATOR_ID

    def run(
        self,
        *,
        target: str,
        drug: str,
        tissue: str = "plasma",
        dose_mg: float = 100.0,
        uniprot: str | None = None,
        fu: float | None = None,
    ) -> SimResult:
        result = run_simulation(
            target=target, drug=drug, tissue=tissue, dose_mg=dose_mg,
            uniprot=uniprot, fu=fu,
        )
        result.estimator = self.id
        return result


# Ligand efficiency of a *typical* small-molecule hit: ~0.3 kcal/mol of binding free
# energy per heavy (non-hydrogen) atom. A textbook rule of thumb, not a fitted model.
_LE_KCAL_PER_HEAVY_ATOM = 0.3
# Clamp the baseline ΔG to a plausible small-molecule window so a very large or very
# small ligand cannot produce a nonsensical affinity. Purely a guard rail on a heuristic.
_BASELINE_DG_BOUNDS = (-12.0, -3.0)


class LigandEfficiencyBaseline:
    """A deliberately naive, **structure-free** control — not a competing docking method.

    It fetches the ligand SMILES, counts heavy atoms, and estimates binding free energy
    from a single textbook rule of thumb — ligand efficiency ≈ 0.3 kcal/mol per heavy
    atom — then runs the *same* PK/PD model as the docking estimator so the two are
    comparable end to end. It never touches a protein structure, never docks, and never
    resolves a pocket.

    Why it exists: it is the floor of the head-to-head. Docking is expensive (fetch a
    structure, prepare a receptor, run Vina); if its ranking of trials is no better than
    "bigger molecule ⇒ tighter binder", that expense bought nothing. So this baseline is
    the control the docking estimator has to beat, per the thesis that the physics must
    add *incremental* value over cheap priors.

    What it is NOT: a physical model of binding. Heavy-atom count is not affinity; the
    number is a size proxy, reported at low confidence and flagged as such in
    ``warnings``. Treating its ΔG as a real affinity would be exactly the overclaim the
    project is built to avoid.
    """

    id = "ligand-efficiency-baseline@1"

    def run(
        self,
        *,
        target: str,
        drug: str,
        tissue: str = "plasma",
        dose_mg: float = 100.0,
        uniprot: str | None = None,
        fu: float | None = None,
    ) -> SimResult:
        result = SimResult(
            target=target, drug=drug, tissue=tissue, dose_mg=dose_mg, estimator=self.id
        )
        result.warnings.append(
            "structure-free baseline control: DeltaG is a heavy-atom size proxy "
            "(ligand efficiency ~0.3 kcal/mol/atom), NOT a docked affinity"
        )
        try:
            from rdkit import Chem  # lazy, matches app.simulation

            smiles = fetch_ligand_smiles(drug)
            result.provenance["smiles"] = smiles
            mol = Chem.MolFromSmiles(smiles)
            if mol is None:
                raise RuntimeError(f"RDKit could not parse SMILES: {smiles}")

            heavy_atoms = mol.GetNumHeavyAtoms()
            desc = ligand_descriptors(Chem.AddHs(mol))
            result.provenance["descriptors"] = {k: round(v, 3) for k, v in desc.items()}
            result.provenance["heavy_atoms"] = heavy_atoms
            result.provenance["structure_source"] = "none (ligand-only baseline)"

            lo, hi = _BASELINE_DG_BOUNDS
            dg = min(hi, max(lo, -_LE_KCAL_PER_HEAVY_ATOM * heavy_atoms))
            kd_nM = kd_from_dg(dg)
            result.binding_affinity_kcal_mol = round(dg, 3)
            result.kd_nM = round(kd_nM, 3)

            # Same free-drug occupancy treatment as the docking estimator, so the
            # head-to-head compares like with like.
            fu_value, fu_source = resolve_fu(drug, fu)
            result.provenance["fu"] = fu_value
            result.provenance["fu_source"] = fu_source
            if fu_source == "unknown":
                result.warnings.append(
                    "no plasma fraction-unbound (fu) for this drug; occupancy is a "
                    "TOTAL-drug upper bound (fu=1), not free-drug engagement"
                )

            pkpd = run_pkpd(
                dose_mg=dose_mg, mol_weight=desc["mw"], kd_nM=kd_nM,
                tissue=tissue, fu=fu_value,
            )
            result.cmax_ng_ml = round(pkpd["cmax_ng_ml"], 3)
            result.auc_ng_h_ml = round(pkpd["auc_ng_h_ml"], 3)
            result.target_occupancy_pct = round(pkpd["target_occupancy_pct"], 2)

            violations = sum(
                [desc["mw"] > 500, desc["logp"] > 5, desc["hbd"] > 5, desc["hba"] > 10]
            )
            result.druglikeness_flag = violations >= 2
            # Low by construction: this is a size proxy with no structure and no pocket.
            result.confidence = 0.2
        except Exception as exc:  # noqa: BLE001 — surface failures as data, like run_simulation
            result.error = f"{type(exc).__name__}: {exc}"
        return result


# The registry of runnable estimators, keyed by id. Add an entry here and it is
# immediately CLI-selectable and service-selectable — no other wiring required.
REGISTRY: dict[str, Estimator] = {
    est.id: est
    for est in (VinaDockingEstimator(), LigandEfficiencyBaseline())
}

# The estimator used when none is named — the real docking pipeline, so existing
# behaviour is unchanged unless a caller opts into the comparison.
DEFAULT_ESTIMATOR_ID = VINA_ESTIMATOR_ID


def get_estimator(estimator_id: str | None = None) -> Estimator:
    """Look up a registered estimator by id (``None`` → the default)."""
    key = estimator_id or DEFAULT_ESTIMATOR_ID
    try:
        return REGISTRY[key]
    except KeyError:
        known = ", ".join(sorted(REGISTRY)) or "(none registered)"
        raise KeyError(f"unknown estimator '{key}'; registered: {known}") from None


def list_estimators() -> list[str]:
    """Ids of all registered estimators, sorted for stable output."""
    return sorted(REGISTRY)
