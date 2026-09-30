"""Tests for the Simply-Fi cloud client — no live credentials required."""

from __future__ import annotations

import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.candy.client.cloud import (
    CloudApplianceData,
    SimplyFiCloudError,
    _authenticate,
    _fetch_appliances,
    _fetch_downloadable_programs,
    _generate_pkce_pair,
    _match_appliance,
    base64url,
    fetch_appliance_data,
)

_TOKENS = {"id_token": "id-tok", "cognito_token": "cog-tok"}


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_base64url_no_padding():
    result = base64url(b"\xff\xfe\xfd")
    assert "=" not in result
    assert "+" not in result
    assert "/" not in result


def test_generate_pkce_pair():
    verifier, challenge = _generate_pkce_pair()
    assert isinstance(verifier, str)
    assert isinstance(challenge, str)
    assert "=" not in verifier
    assert "=" not in challenge
    assert challenge == base64url(hashlib.sha256(verifier.encode()).digest())


# ---------------------------------------------------------------------------
# _match_appliance (pure, no I/O)
# ---------------------------------------------------------------------------


def _appliance_entry(ip=None, key="secret-key", programs=None):
    appliance = {
        "mac_address": "AA:BB:CC:DD:EE:FF",
        "encryption_key": key,
        "appliance_model": "RO41274DWMSE/1-S",
        "sixteen_digits_code": "SN12345678901234",
        "purchase_date": "2024-01-01",
        "interface_type": "RAPIDO_4DIG_STM_NEL",
        "programs": (
            programs
            if programs is not None
            else [
                {
                    "program": {
                        "id": "7e661414-b751-4483-b537-9bf8cf19ea00",
                        "name": "RESISTANT_COTTONS",
                    }
                }
            ]
        ),
        "current_status_parameters": {"ip_address": ip} if ip else {},
    }
    return {"appliance": appliance}


def test_match_appliance_by_ip():
    appliances = [_appliance_entry(ip="10.0.0.1"), _appliance_entry(ip="10.0.0.2")]
    result = _match_appliance(appliances, "10.0.0.1", [])
    assert isinstance(result, CloudApplianceData)
    assert result.mac_address == "AA:BB:CC:DD:EE:FF"
    assert result.encryption_key == "secret-key"
    assert result.downloadable_programs == []


def test_match_appliance_single_fallback():
    appliances = [_appliance_entry(ip=None)]
    result = _match_appliance(appliances, "192.168.1.100", [{"id": 99}])
    assert isinstance(result, CloudApplianceData)
    assert result.downloadable_programs == [{"id": 99}]


def test_match_appliance_no_match_multiple():
    appliances = [_appliance_entry(ip="10.0.0.1"), _appliance_entry(ip="10.0.0.2")]
    with pytest.raises(SimplyFiCloudError, match="No Simply-Fi appliance matched"):
        _match_appliance(appliances, "10.0.0.99", [])


def test_match_appliance_missing_encryption_key():
    appliances = [_appliance_entry(ip="10.0.0.1", key="")]
    with pytest.raises(SimplyFiCloudError, match="missing encryption_key"):
        _match_appliance(appliances, "10.0.0.1", [])


def test_match_appliance_missing_programs():
    appliances = [_appliance_entry(ip="10.0.0.1", programs=[])]
    with pytest.raises(SimplyFiCloudError, match="missing programs"):
        _match_appliance(appliances, "10.0.0.1", [])


# ---------------------------------------------------------------------------
# HTTP mock helpers
# ---------------------------------------------------------------------------


def _make_resp(status: int, json_data=None, text: str = "error"):
    resp = MagicMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    resp.text = AsyncMock(return_value=text)
    resp.__aenter__ = AsyncMock(return_value=resp)
    resp.__aexit__ = AsyncMock(return_value=False)
    return resp


def _make_session(get_resps=None, post_resps=None):
    session = MagicMock()
    if get_resps is not None:
        it = iter(get_resps)
        session.get = MagicMock(side_effect=lambda *a, **kw: next(it))
    if post_resps is not None:
        it2 = iter(post_resps)
        session.post = MagicMock(side_effect=lambda *a, **kw: next(it2))
    return session


# ---------------------------------------------------------------------------
# _authenticate
# ---------------------------------------------------------------------------

_GOOD_AUTHORIZE = {"session_id": "sess-abc"}
_GOOD_TOKEN = {"tokens": _TOKENS}


async def test_authenticate_success():
    session = _make_session(
        get_resps=[_make_resp(200, _GOOD_AUTHORIZE)],
        post_resps=[_make_resp(200, _GOOD_TOKEN)],
    )
    tokens = await _authenticate(session, "user@example.com", "pass")
    assert tokens["id_token"] == "id-tok"
    assert tokens["cognito_token"] == "cog-tok"


async def test_authenticate_authorize_non_200():
    session = _make_session(get_resps=[_make_resp(401, text="Unauthorized")])
    with pytest.raises(SimplyFiCloudError, match="CIAM authorize failed"):
        await _authenticate(session, "u", "p")


async def test_authenticate_missing_session_id():
    session = _make_session(get_resps=[_make_resp(200, {})])
    with pytest.raises(SimplyFiCloudError, match="missing session_id"):
        await _authenticate(session, "u", "p")


async def test_authenticate_token_non_200():
    session = _make_session(
        get_resps=[_make_resp(200, _GOOD_AUTHORIZE)],
        post_resps=[_make_resp(500, text="Server Error")],
    )
    with pytest.raises(SimplyFiCloudError, match="CIAM token exchange failed"):
        await _authenticate(session, "u", "p")


async def test_authenticate_missing_tokens():
    # tokens dict present but missing cognito_token
    session = _make_session(
        get_resps=[_make_resp(200, _GOOD_AUTHORIZE)],
        post_resps=[_make_resp(200, {"tokens": {"id_token": "x"}})],
    )
    with pytest.raises(SimplyFiCloudError, match="missing expected fields"):
        await _authenticate(session, "u", "p")


# ---------------------------------------------------------------------------
# _fetch_appliances
# ---------------------------------------------------------------------------


async def test_fetch_appliances_success():
    appliances = [{"appliance": {"mac_address": "AA:BB:CC:DD:EE:FF"}}]
    session = _make_session(get_resps=[_make_resp(200, appliances)])
    result = await _fetch_appliances(session, _TOKENS)
    assert result == appliances


async def test_fetch_appliances_non_200():
    session = _make_session(get_resps=[_make_resp(403, text="Forbidden")])
    with pytest.raises(SimplyFiCloudError, match="appliances fetch failed"):
        await _fetch_appliances(session, _TOKENS)


async def test_fetch_appliances_non_list_response():
    session = _make_session(get_resps=[_make_resp(200, {"error": "unexpected"})])
    with pytest.raises(
        SimplyFiCloudError, match="Unexpected appliances response format"
    ):
        await _fetch_appliances(session, _TOKENS)


# ---------------------------------------------------------------------------
# _fetch_downloadable_programs
# ---------------------------------------------------------------------------


async def test_fetch_downloadable_programs_list_response():
    programs = [
        {
            "wm_wd_program": {
                "id": "899838a1-1d15-4d15-814e-a6894c279be6",
                "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_BED_LINEN",
            }
        },
        {
            "wm_wd_program": {
                "id": "e40658f7-883e-42ab-8255-5aff9bfa528c",
                "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_NEW_CLOTHES",
            }
        },
    ]
    session = _make_session(get_resps=[_make_resp(200, programs)])
    result = await _fetch_downloadable_programs(session, _TOKENS)
    assert result == [
        {
            "id": "899838a1-1d15-4d15-814e-a6894c279be6",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_BED_LINEN",
        },
        {
            "id": "e40658f7-883e-42ab-8255-5aff9bfa528c",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_NEW_CLOTHES",
        },
    ]


async def test_fetch_downloadable_programs_dict_wrapper():
    data = {
        "wm_wd_programs": [
            {
                "id": "52ab9121-e1be-47db-b419-1f468e5ad830",
                "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
            },
            {
                "id": "2db4e142-ff5b-42ea-a417-10ffb6a3ce28",
                "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_GYM_FIT",
            },
        ]
    }
    session = _make_session(get_resps=[_make_resp(200, data)])
    result = await _fetch_downloadable_programs(session, _TOKENS)
    assert result == [
        {
            "id": "52ab9121-e1be-47db-b419-1f468e5ad830",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_CASHMERE",
        },
        {
            "id": "2db4e142-ff5b-42ea-a417-10ffb6a3ce28",
            "name": "DUAL_WM_WD_PROGRAM_DOWNLOAD_NAME_GYM_FIT",
        },
    ]


async def test_fetch_downloadable_programs_non_200():
    session = _make_session(get_resps=[_make_resp(403, text="Forbidden")])
    with pytest.raises(SimplyFiCloudError, match="downloadable programs fetch failed"):
        await _fetch_downloadable_programs(session, _TOKENS)


# ---------------------------------------------------------------------------
# fetch_appliance_data (end-to-end with patched internals)
# ---------------------------------------------------------------------------


async def test_fetch_appliance_data_delegates():
    entry = _appliance_entry(ip="10.0.0.1")
    with (
        patch(
            "custom_components.candy.client.cloud._authenticate",
            AsyncMock(return_value=_TOKENS),
        ),
        patch(
            "custom_components.candy.client.cloud._fetch_appliances",
            AsyncMock(return_value=[entry]),
        ),
        patch(
            "custom_components.candy.client.cloud._fetch_downloadable_programs",
            AsyncMock(return_value=[]),
        ),
    ):
        result = await fetch_appliance_data(
            MagicMock(), "user@x.com", "pass", "10.0.0.1"
        )

    assert isinstance(result, CloudApplianceData)
    assert result.encryption_key == "secret-key"
    assert result.downloadable_programs == []
