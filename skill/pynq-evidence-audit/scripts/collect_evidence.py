"""Collect explicit file identities and Linux resource snapshots without loading PL."""

import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def describe_file(path, expected_hash=None):
    path = Path(path).resolve(strict=True)
    digest = sha256_file(path)
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": digest,
            "expected_sha256": expected_hash,
            "hash_matches": None if expected_hash is None else digest == expected_hash.lower()}


def describe_hwh(path):
    path = Path(path)
    if path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("HWH exceeds the supported 64 MiB inspection limit")
    root = ET.parse(path).getroot()
    modules = [dict(node.attrib) for node in root.iter("MODULE")]
    return {
        "root_tag": root.tag, "root_attributes": dict(root.attrib),
        "system_info": [dict(n.attrib) for n in root.iter("SYSTEMINFO")],
        "module_nodes": len(modules),
        "ip_types": dict(Counter(m.get("VLNV", m.get("MODTYPE", "unknown")) for m in modules)),
        "modules": modules,
        "interpretation": "hardware metadata only; not synthesized resource utilization",
    }


def read_process(pid, proc_root=Path("/proc")):
    directory = proc_root / str(pid)
    fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
    result = {"pid": pid, "cpu_ticks": int(fields[11]) + int(fields[12]),
              "start_ticks": int(fields[19])}
    for line in (directory / "status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in ("VmRSS", "VmHWM", "VmSize", "VmSwap"):
            result[key + "_bytes"] = int(value.split()[0]) * 1024
        elif key == "Threads":
            result["threads"] = int(value.strip())
    return result


def read_system(proc_root=Path("/proc")):
    fields = (proc_root / "stat").read_text().splitlines()[0].split()
    if fields[0] != "cpu":
        raise ValueError("unexpected /proc/stat header")
    ticks = list(map(int, fields[1:]))
    result = {"total_ticks": sum(ticks[:8]), "idle_ticks": ticks[3] + ticks[4]}
    for line in (proc_root / "meminfo").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree", "CmaTotal", "CmaFree"):
            result[key + "_bytes"] = int(value.split()[0]) * 1024
    return result


def interval_metrics(previous, current, hz, cpu_count):
    elapsed = current["monotonic"] - previous["monotonic"]
    if elapsed <= 0:
        raise ValueError("sampling clock did not advance")
    before, after = previous["system"], current["system"]
    total = after["total_ticks"] - before["total_ticks"]
    idle = after["idle_ticks"] - before["idle_ticks"]
    if total <= 0 or idle < 0 or idle > total:
        raise ValueError("invalid system CPU counters")
    result = {"elapsed_seconds": elapsed, "system_cpu_percent": 100.0 * (total - idle) / total}
    a, b = previous.get("process"), current.get("process")
    if a is not None and b is not None:
        if a["start_ticks"] != b["start_ticks"] or a["pid"] != b["pid"]:
            raise ValueError("PID identity changed; do not combine different processes")
        used = (b["cpu_ticks"] - a["cpu_ticks"]) / hz
        if used < 0:
            raise ValueError("process CPU counters went backwards")
        result.update(process_cpu_percent_one_core=100 * used / elapsed,
                      process_cpu_percent_machine=100 * used / elapsed / cpu_count)
    return result


def service_status(name):
    command = ["systemctl", "show", name, "-p", "MainPID", "-p", "ActiveState",
               "-p", "SubState", "-p", "UnitFileState", "-p", "NRestarts"]
    process = subprocess.run(command, text=True, capture_output=True, timeout=10, check=True)
    return dict(line.split("=", 1) for line in process.stdout.splitlines() if "=" in line)


def summarize(values):
    return {"min": min(values), "mean": statistics.mean(values), "max": max(values)}


def record_issue(report, check, error):
    report["issues"].append({"check": check, "error": str(error)})


def collect(args):
    report = {"schema_version": "pynq_evidence_audit_v0.3",
              "environment": {"platform": platform.platform(), "python": platform.python_version()},
              "input_files": {}, "issues": [], "warnings": [],
              "pl_utilization": {"status": "not_measured", "lut": None, "ff": None,
                                 "bram": None, "dsp": None,
                                 "reason": "requires a matching implementation/synthesis report"}}
    try:
        report["environment"]["pynq_package_version"] = importlib.metadata.version("pynq")
    except importlib.metadata.PackageNotFoundError:
        report["environment"]["pynq_package_version"] = None
    for label in ("bit", "hwh"):
        path = getattr(args, label)
        if path is None:
            continue
        try:
            description = describe_file(path, getattr(args, "expected_" + label + "_sha256"))
            report["input_files"][label] = description
            if description["hash_matches"] is False:
                record_issue(report, label + "_hash", "SHA-256 differs from expected value")
            if label == "hwh":
                metadata = describe_hwh(path)
                report["hwh_metadata"] = metadata
                available = {value for module in metadata["modules"]
                             for key in ("MODTYPE", "VLNV") for value in [module.get(key)] if value}
                missing = sorted(set(args.require_ip) - available)
                report["required_ip_check"] = {"requested": args.require_ip, "missing": missing}
                if missing:
                    record_issue(report, "required_ip", "required IP types missing: " + ", ".join(missing))
        except (OSError, ValueError, ET.ParseError) as error:
            record_issue(report, label, error)
    if args.bit and args.hwh:
        if Path(args.bit).resolve().with_suffix("") != Path(args.hwh).resolve().with_suffix(""):
            report["warnings"].append("BIT/HWH are not a same-directory same-stem pair; verify provenance")
    if args.state:
        try:
            state = json.loads(Path(args.state).read_text(encoding="utf-8"))
            if not isinstance(state, dict):
                raise ValueError("loaded-state JSON must be an object")
            selected = {key: state.get(key) for key in
                        ("bitfile_name", "active_name", "bitfile_hash")}
            selected["evidence_type"] = "software_record_only; not hardware configuration readback"
            if args.bit:
                if not state.get("bitfile_name"):
                    record_issue(report, "loaded_state", "no bitfile_name in software state record")
                else:
                    selected["recorded_path_matches"] = (
                        Path(state["bitfile_name"]).resolve() == Path(args.bit).resolve())
                    if not selected["recorded_path_matches"]:
                        record_issue(report, "loaded_state", "recorded bit path does not match requested BIT")
            report["loaded_state"] = selected
        except (OSError, ValueError, TypeError) as error:
            record_issue(report, "loaded_state", error)
    pid = args.pid
    if args.service:
        try:
            before = service_status(args.service)
            report["service_before"] = before
            service_pid = int(before.get("MainPID", "0"))
            if before.get("ActiveState") != "active" or service_pid <= 0:
                raise ValueError("service is not active with a live MainPID")
            if pid is not None and pid != service_pid:
                raise ValueError("explicit PID differs from service MainPID")
            pid = service_pid
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            record_issue(report, "service_before", error)
    report["sample_pid"] = pid
    if platform.system() == "Linux":
        for name in ("state", "name"):
            path = Path("/sys/class/fpga_manager/fpga0") / name
            try:
                report.setdefault("fpga_manager", {})[name] = path.read_text().strip()
            except OSError as error:
                report["warnings"].append("FPGA manager " + name + ": " + str(error))
    if args.samples:
        if platform.system() != "Linux":
            record_issue(report, "sampling", "Linux /proc is required; use --samples 0 for file-only audit")
        else:
            samples = []
            try:
                hz, cpu_count = os.sysconf("SC_CLK_TCK"), os.cpu_count() or 1
                report["sampling_method"] = {
                    "interval_requested_seconds": args.interval, "intervals_requested": args.samples,
                    "logical_cpu_count": cpu_count, "clock_ticks_per_second": hz,
                    "system_cpu_basis": "all logical CPUs together = 100%; idle+iowait are nonbusy",
                    "process_cpu_basis": "one logical CPU = 100%; machine-normalized field also supplied",
                    "rss_semantics": "resident pages including shared pages; not total unique DDR",
                }
                for index in range(args.samples + 1):
                    if index:
                        time.sleep(args.interval)
                    point = {"monotonic": time.monotonic(), "system": read_system()}
                    if pid is not None:
                        point["process"] = read_process(pid)
                    samples.append(point)
                intervals = [interval_metrics(a, b, hz, cpu_count)
                             for a, b in zip(samples, samples[1:])]
                report["intervals"] = intervals
                report["summary"] = {"window_seconds": sum(x["elapsed_seconds"] for x in intervals),
                                     "system_cpu_percent": summarize([x["system_cpu_percent"] for x in intervals])}
                if pid is not None:
                    report["summary"]["process_cpu_percent_one_core"] = summarize(
                        [x["process_cpu_percent_one_core"] for x in intervals])
                    rss = [x["process"]["VmRSS_bytes"] for x in samples if "VmRSS_bytes" in x["process"]]
                    if rss:
                        report["summary"]["process_rss_bytes"] = summarize(rss)
                report["summary"]["peak_scope"] = "sampled window only; not a proven live-inference peak"
            except (OSError, ValueError, IndexError, KeyError) as error:
                record_issue(report, "sampling", error)
            finally:
                report["samples"] = samples
    if args.service:
        try:
            after = service_status(args.service)
            report["service_after"] = after
            before = report.get("service_before", {})
            if after.get("ActiveState") != "active" or after.get("MainPID") != before.get("MainPID"):
                record_issue(report, "service_after", "service state or MainPID changed during observation")
            if before.get("NRestarts") != after.get("NRestarts"):
                record_issue(report, "service_after", "NRestarts changed during observation")
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            record_issue(report, "service_after", error)
    for label, description in report["input_files"].items():
        try:
            description["unchanged_at_end"] = sha256_file(description["path"]) == description["sha256"]
            if not description["unchanged_at_end"]:
                record_issue(report, label + "_changed", "file changed during observation")
        except OSError as error:
            record_issue(report, label + "_recheck", error)
    report["status"] = "ok" if not report["issues"] else "issues_found"
    report["status_scope"] = "requested checks only; not functional or end-to-end acceptance"
    return report


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bit", type=Path)
    parser.add_argument("--hwh", type=Path)
    parser.add_argument("--state", type=Path, help="optional explicit PYNQ loaded-state JSON")
    parser.add_argument("--expected-bit-sha256")
    parser.add_argument("--expected-hwh-sha256")
    parser.add_argument("--require-ip", action="append", default=[], help="exact MODTYPE or VLNV")
    parser.add_argument("--pid", type=int)
    parser.add_argument("--service")
    parser.add_argument("--samples", type=int, default=6, help="interval count; 0 disables Linux sampling")
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--output", type=Path, help="new JSON file; omitted prints JSON to stdout")
    args = parser.parse_args(argv)
    if not any((args.bit, args.hwh, args.pid, args.service)):
        parser.error("specify --bit, --hwh, --pid, or --service")
    if args.pid is not None and args.pid <= 0:
        parser.error("--pid must be positive")
    if not 0 <= args.samples <= 300 or not math.isfinite(args.interval) or not 0.02 <= args.interval <= 5:
        parser.error("require samples 0..300 and finite interval 0.02..5 seconds")
    if args.service and not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.@:-]*", args.service):
        parser.error("--service must be a literal systemd unit name, not a path or option")
    if args.require_ip and not args.hwh:
        parser.error("--require-ip needs --hwh")
    for label in ("bit", "hwh"):
        digest = getattr(args, "expected_" + label + "_sha256")
        if digest and (getattr(args, label) is None or not re.fullmatch(r"[0-9a-fA-F]{64}", digest)):
            parser.error("expected SHA-256 needs the corresponding input and 64 hexadecimal characters")
    if args.output:
        resolved_output = args.output.resolve()
        if args.output.exists():
            parser.error("--output already exists; choose a new file")
        if resolved_output in {x.resolve() for x in (args.bit, args.hwh, args.state) if x is not None}:
            parser.error("--output must not overwrite an input")
    return args


def main(argv=None):
    args = parse_args(argv)
    report = collect(args)
    encoded = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(encoded)
        print(json.dumps({"output": str(args.output), "status": report["status"]}))
    else:
        print(encoded, end="")
    return 0 if report["status"] == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
