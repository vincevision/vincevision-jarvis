from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from pathlib import Path


@dataclass
class AuthorizationContext:
    project_id: str
    authorized_scope: List[str] = field(default_factory=list)
    approved_windows: List[str] = field(default_factory=list)
    approver: str = ""
    notes: str = ""
    active: bool = False

    def is_valid(self) -> bool:
        return bool(self.project_id and self.authorized_scope and self.approver and self.active)


@dataclass
class Finding:
    title: str
    severity: str
    description: str
    evidence: List[str] = field(default_factory=list)
    remediation: List[str] = field(default_factory=list)
    standards: List[str] = field(default_factory=list)


class AssessmentPlugin:
    name: str = "base"
    version: str = "0.1"

    def validate_scope(self, authorization: AuthorizationContext) -> bool:
        return authorization.is_valid()

    def run(self, authorization: AuthorizationContext, request: Dict) -> List[Finding]:
        raise NotImplementedError


class AssetDiscoveryPlugin(AssessmentPlugin):
    name = "asset_discovery"
    version = "0.1"

    def run(self, authorization: AuthorizationContext, request: Dict) -> List[Finding]:
        if not self.validate_scope(authorization):
            return [Finding(
                title="Authorization required",
                severity="info",
                description="Active discovery requires explicit authorization and an approved scope.",
                remediation=["Provide project authorization and approved scope before execution."],
                standards=["NIST CSF", "ISO 27001"],
            )]

        return [Finding(
            title="Asset inventory collected",
            severity="info",
            description="Discovery workflow would enumerate approved hosts and services in this implementation.",
            evidence=[f"Scope: {', '.join(authorization.authorized_scope)}"],
            remediation=["Review discovered assets and confirm their ownership and criticality."],
            standards=["CIS Controls", "NIST CSF"],
        )]


class VulnerabilityScannerPlugin(AssessmentPlugin):
    name = "vulnerability_scanning"
    version = "0.1"

    def run(self, authorization: AuthorizationContext, request: Dict) -> List[Finding]:
        if not self.validate_scope(authorization):
            return [Finding(
                title="Authorization required",
                severity="info",
                description="Vulnerability scanning requires explicit approval and in-scope targets.",
                remediation=["Submit scoped approval before running scans."],
                standards=["NIST CSF", "CIS Controls"],
            )]

        return [Finding(
            title="Scan plan prepared",
            severity="info",
            description="The scanner would evaluate approved targets for CVEs, misconfigurations, and exposed services.",
            remediation=["Review findings and prioritize remediation by asset criticality."],
            standards=["MITRE ATT&CK", "NIST CSF"],
        )]


class SecurityAssessmentPlatform:
    def __init__(self, storage_dir: Optional[str] = None):
        self.storage_dir = Path(storage_dir or "reports")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.plugins: Dict[str, AssessmentPlugin] = {
            "asset_discovery": AssetDiscoveryPlugin(),
            "vulnerability_scanning": VulnerabilityScannerPlugin(),
        }

    def run_module(self, module_name: str, authorization: AuthorizationContext, request: Dict) -> List[Finding]:
        plugin = self.plugins.get(module_name)
        if not plugin:
            return [Finding(
                title="Unknown module",
                severity="error",
                description=f"The module '{module_name}' is not available.",
                remediation=["Select an installed plugin module."],
                standards=["NIST CSF"],
            )]
        return plugin.run(authorization, request)

    def list_modules(self) -> List[str]:
        return sorted(self.plugins.keys())

    def save_report(self, report_name: str, findings: List[Finding]) -> Path:
        report_path = self.storage_dir / f"{report_name}.json"
        payload = {
            "findings": [
                {
                    "title": item.title,
                    "severity": item.severity,
                    "description": item.description,
                    "evidence": item.evidence,
                    "remediation": item.remediation,
                    "standards": item.standards,
                }
                for item in findings
            ]
        }
        report_path.write_text(__import__("json").dumps(payload, indent=2), encoding="utf-8")
        return report_path
