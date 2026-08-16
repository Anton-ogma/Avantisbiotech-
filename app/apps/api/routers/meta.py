from __future__ import annotations

from fastapi import APIRouter, Depends

from contracts.schemas import ConfigVersions, ParamInfo, PlatformInfo, ProbeInfo

from ..services.bundle import bundle_from_settings
from ..settings import Settings, get_settings

router = APIRouter(tags=["meta"])


@router.get("/platform", response_model=PlatformInfo)
async def platform(s: Settings = Depends(get_settings)) -> PlatformInfo:
    b = bundle_from_settings(s)
    return PlatformInfo(
        intended_use=s.intended_use,
        registration_number=s.registration_number,
        versions=ConfigVersions(**b.versions),
        protocol_version=b.probes.version,
        thresholds_are_demo=b.thresholds.is_demo,
        norms_defined=not b.norms.empty,
        banners=s.banners,
    )


@router.get("/params", response_model=list[ParamInfo])
async def params(s: Settings = Depends(get_settings)) -> list[ParamInfo]:
    b = bundle_from_settings(s)
    return [
        ParamInfo(
            code=p.code, label_ru=p.label_ru, unit=p.unit, domain=p.domain,
            direction=p.direction, in_pi=p.in_pi, sdc=b.thresholds.sdc(p.code),
            norm_defined=b.norms.get(p.code) is not None,
            direction_evidence=p.direction_evidence,
        )
        for p in sorted(b.registry.params.values(), key=lambda x: (x.domain, x.code))
    ]


@router.get("/probes", response_model=list[ProbeInfo])
async def probes(s: Settings = Depends(get_settings)) -> list[ProbeInfo]:
    b = bundle_from_settings(s)
    return [
        ProbeInfo(
            code=p.code, label_ru=p.label_ru, group=p.group, role=p.role,
            settle_sec=p.settle_sec, carryover_min=p.carryover_min,
            is_neutral=p.is_neutral, shams_group=p.shams_group,
        )
        for p in sorted(b.probes.probes.values(), key=lambda x: (x.group, x.role, x.code))
    ]
