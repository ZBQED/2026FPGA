"""Compare numeric NPY/NPZ outputs with an explicitly supplied golden reference."""

import argparse
from decimal import Decimal, localcontext
from fractions import Fraction
import json
import math
from pathlib import Path
import numpy as np


def rational(value):
    """Represent a finite scalar without a float64 intermediate."""
    if isinstance(value, (int, np.integer)):
        return Fraction(int(value))
    numerator, denominator = value.as_integer_ratio()
    return Fraction(int(numerator), int(denominator))


def compare_mixed(reference, actual, atol, rtol, report):
    """Compare integer/float pairs exactly, including the tolerance boundary."""
    absolute, relative = rational(atol), rational(rtol)
    mismatch_count, first, maximum = 0, None, Fraction(0)
    for index, (ref, out) in enumerate(zip(reference.flat, actual.flat)):
        ref_value, out_value = rational(ref), rational(out)
        difference = abs(out_value - ref_value)
        maximum = max(maximum, difference)
        if difference > absolute + relative * abs(ref_value):
            mismatch_count += 1
            if first is None:
                first = list(map(int, np.unravel_index(index, reference.shape)))
    with localcontext() as context:
        context.prec = 17
        maximum_text = format(Decimal(maximum.numerator) / Decimal(maximum.denominator), ".17g")
    report.update(status="failed" if mismatch_count else "passed",
                  element_count=int(reference.size), mismatch_count=mismatch_count,
                  max_abs_error=maximum_text, first_mismatch_index=first,
                  comparison_method="exact_rational_mixed_integer_float")
    return report


def load_array(path, key=None):
    loaded = np.load(path, allow_pickle=False)
    if isinstance(loaded, np.lib.npyio.NpzFile):
        with loaded:
            if key is None:
                raise ValueError("NPZ input requires an explicit --key")
            return np.array(loaded[key], copy=True)
    if key is not None:
        raise ValueError("--key is only valid when both inputs are NPZ")
    return loaded


def compare(reference, actual, atol, rtol):
    report = {"reference_shape": list(reference.shape), "actual_shape": list(actual.shape),
              "reference_dtype": str(reference.dtype), "actual_dtype": str(actual.dtype),
              "atol": atol, "rtol": rtol, "status": "failed"}
    if not all(math.isfinite(x) and x >= 0 for x in (atol, rtol)):
        report["reason"] = "invalid_tolerance"
        return report
    if reference.shape != actual.shape:
        report["reason"] = "shape_mismatch"
        return report
    if reference.size == 0:
        report["reason"] = "empty_arrays_are_not_validation_evidence"
        return report
    if reference.dtype.kind not in "iuf" or actual.dtype.kind not in "iuf":
        report["reason"] = "unsupported_dtype; use real integer or floating arrays"
        return report
    if not np.isfinite(reference).all() or not np.isfinite(actual).all():
        report["reason"] = "nonfinite_input"
        return report
    if (reference.dtype.kind in "iu") != (actual.dtype.kind in "iu"):
        return compare_mixed(reference, actual, atol, rtol, report)
    ref, out = reference.astype(np.longdouble), actual.astype(np.longdouble)
    with np.errstate(over="ignore", invalid="ignore"):
        if reference.dtype.kind in "iu" and actual.dtype.kind in "iu":
            exact_difference = np.abs(actual.astype(object) - reference.astype(object))
            difference = np.asarray(exact_difference, dtype=np.longdouble)
        else:
            difference = np.abs(out - ref)
        tolerance = np.longdouble(atol) + np.longdouble(rtol) * np.abs(ref)
    if not np.isfinite(difference).all() or not np.isfinite(tolerance).all():
        report["reason"] = "comparison_overflow"
        return report
    bad = difference > tolerance
    # Also compare integer pairs exactly before any floating conversion.
    if reference.dtype.kind in "iu" and actual.dtype.kind in "iu" and atol == 0 and rtol == 0:
        bad = np.asarray(reference, dtype=object) != np.asarray(actual, dtype=object)
    report.update(element_count=int(ref.size), mismatch_count=int(np.count_nonzero(bad)),
                  max_abs_error=format(np.max(difference), ".17g"),
                  status="passed" if not np.any(bad) else "failed")
    report["first_mismatch_index"] = list(map(int, np.unravel_index(np.flatnonzero(bad)[0], bad.shape))) if np.any(bad) else None
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("actual", type=Path)
    parser.add_argument("--key")
    parser.add_argument("--atol", type=float, required=True)
    parser.add_argument("--rtol", type=float, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not all(math.isfinite(x) and x >= 0 for x in (args.atol, args.rtol)):
        parser.error("atol and rtol must be finite and nonnegative")
    if args.output and (args.output.exists() or args.output.resolve() in
                        (args.reference.resolve(), args.actual.resolve())):
        parser.error("--output must be a new file, not an input")
    try:
        report = compare(load_array(args.reference, args.key), load_array(args.actual, args.key),
                         args.atol, args.rtol)
    except (OSError, ValueError, KeyError, TypeError, EOFError) as error:
        report = {"status": "failed", "reason": str(error)}
    report.update(reference_path=str(args.reference), actual_path=str(args.actual),
                  interpretation="array equality/tolerance check only; not classifier accuracy or task acceptance")
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
