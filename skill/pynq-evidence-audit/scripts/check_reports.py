"""Check supported English Vivado utilization/timing reports; never infer timing closure."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def number(value):
    value = float(value.replace(",", ""))
    if not math.isfinite(value):
        raise ValueError("nonfinite report number")
    return value


def header(text, name):
    match = re.search(r"^\|\s*" + re.escape(name) + r"\s*:\s*(.+)$", text, re.M)
    if not match:
        raise ValueError("missing report header: " + name)
    return match[1].strip()


def utilization(text):
    aliases = {"Slice LUTs": "lut", "CLB LUTs": "lut", "Slice Registers": "ff",
               "CLB Registers": "ff", "Block RAM Tile": "bram", "DSPs": "dsp"}
    columns, result = None, {}
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [x.strip() for x in line.strip().strip("|").split("|")]
        if "Site Type" in cells and "Available" in cells:
            columns = cells
        key = aliases.get(cells[0].rstrip("*"))
        if key and columns:
            values = dict(zip(columns, cells))
            used, available = number(values["Used"]), number(values["Available"])
            prohibited = number(values.get("Prohibited", "0") or "0")
            if used < 0 or available <= 0 or not 0 <= prohibited < available:
                raise ValueError("invalid resource capacity: " + key)
            item = {"used": used, "available": available, "prohibited": prohibited,
                    "percent": 100 * used / (available - prohibited)}
            if key in result and result[key] != item:
                raise ValueError("inconsistent duplicate resource row: " + key)
            result[key] = item
    if set(result) != {"lut", "ff", "bram", "dsp"}:
        raise ValueError("unsupported/missing resource rows; no zero-fill allowed")
    return result


def timing(text):
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip().startswith("WNS(ns)")]
    if len(starts) != 1:
        raise ValueError("expected one Design Timing Summary table")
    rows = [line.split() for line in lines[starts[0] + 1:starts[0] + 5]
            if re.match(r"^\s*[-+]?\d", line)]
    if len(rows) != 1 or len(rows[0]) != 12:
        raise ValueError("unsupported timing summary; require setup, hold and pulse-width columns")
    keys = ("wns_ns", "tns_ns", "setup_failing", "setup_total", "whs_ns", "ths_ns",
            "hold_failing", "hold_total", "wpws_ns", "tpws_ns", "pulse_failing", "pulse_total")
    result = dict(zip(keys, map(number, rows[0])))
    checks = {}
    for key, value in re.findall(r"checking (\w+)\s*\((\d+)\)", text):
        if key in checks and checks[key] != int(value):
            raise ValueError("inconsistent check_timing counts")
        checks[key] = int(value)
    required = {"no_clock", "unconstrained_internal_endpoints", "no_input_delay", "no_output_delay",
                "multiple_clock", "generated_clocks", "loops", "partial_input_delay",
                "partial_output_delay", "latch_loops"}
    if not required <= checks.keys():
        raise ValueError("missing check_timing coverage section")
    result["constraint_checks"] = checks
    return result


def check(util_text, timing_text, max_percent):
    issues = []
    resources, times = utilization(util_text), timing(timing_text)
    identity = {"utilization": {k: header(util_text, k) for k in ("Design", "Device", "Design State")},
                "timing": {k: header(timing_text, k) for k in ("Design", "Device", "Design State")}}
    if identity["utilization"]["Design"] != identity["timing"]["Design"]:
        issues.append("design names differ")
    def part(value):
        return re.sub(r"-\d.*$", "", value.lower()).removeprefix("xc").replace("-", "")
    if part(identity["utilization"]["Device"]) != part(identity["timing"]["Device"]):
        issues.append("devices differ")
    for source in identity.values():
        if source["Design State"].lower() != "routed":
            issues.append("final acceptance requires Routed reports")
    # Vivado uses different part spelling in the two report types. Preserve both;
    # matching names or parts alone cannot bind a report to a bitstream.
    for key, item in resources.items():
        if item["percent"] > max_percent:
            issues.append(key + " exceeds supplied resource budget")
    for key in ("wns_ns", "whs_ns", "wpws_ns"):
        if times[key] < 0:
            issues.append(key + " violates timing")
    for key in ("tns_ns", "ths_ns", "tpws_ns", "setup_failing", "hold_failing", "pulse_failing"):
        if times[key] != 0:
            issues.append(key + " is nonzero")
    for key in ("setup_total", "hold_total", "pulse_total"):
        if times[key] <= 0:
            issues.append(key + " has no evaluated endpoints")
    for key, count in times["constraint_checks"].items():
        if count:
            issues.append("constraint review required: " + key + "=" + str(count))
    return {"status": "passed" if not issues else "failed", "resources": resources,
            "timing": times, "identity": identity, "max_percent": max_percent, "issues": issues,
            "scope": "report checks only; verify common build, constraints, DRC and bitstream provenance separately"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--utilization", type=Path, required=True)
    parser.add_argument("--timing", type=Path, required=True)
    parser.add_argument("--max-percent", type=float, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if not math.isfinite(args.max_percent) or not 0 < args.max_percent <= 100:
        parser.error("max-percent must be in (0, 100]")
    if args.output and args.output.exists():
        parser.error("output already exists")
    try:
        raw = [p.read_bytes() for p in (args.utilization, args.timing)]
        report = check(*(x.decode("utf-8-sig") for x in raw), args.max_percent)
        report["input_sha256"] = dict(zip(("utilization", "timing"),
                                         (hashlib.sha256(x).hexdigest() for x in raw)))
    except (OSError, ValueError, KeyError) as error:
        report = {"status": "failed", "issues": [str(error)]}
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
    print(encoded, end="")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
