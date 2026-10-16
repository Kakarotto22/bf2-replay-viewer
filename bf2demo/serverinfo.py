"""The server settings block (``DataBlock`` kind 0 = ``ServerInfo``).

Layout of ``ServerInfo::updateFromDataBlock`` 0x080676f0 (the client reader) checked against ``ServerInfo::generateDataBlock``
0x080662f0 (the server writer, which names the ``ServerSettings`` member every value comes from; the member names are the
``sv.*`` commands of ``ServerSettings::save`` 0x080bc940). It is a bit stream, LSB first:

====================  ========================================================================
``u16 n, n bytes``    game name (``sv.serverName``)
``u16 c``             number of welcome message lines, each ``u16 n, n bytes`` (``sv.welcomeMessage``, lines joined by ``|``)
7 x ``bool``          response flag (+0x14), voip server remote (+0x15), allowNoseCam, hitIndicator, tkPunishByDefault,
                      allowFreeCam, allowExternalViews
``u32``               voip server address (``GameLogic::getVoipServerInfo``; the sample servers send 1, never a real address)
``u16`` ``u16``       ``sv.voipServerPort``, ``sv.voipBFClientPort``
``int``               ``sv.voipQuality``
``u16``               ``sv.gameSpyPort``
3 x ``int``           ``sv.radioSpamInterval``, ``radioMaxSpamFlagCount``, ``radioBlockedDurationTime``
2 x ``bool``          +0x36 (``generateDataBlock`` never assigns it; true in every sample), ``sv.votingEnabled``
``u16``               ``sv.numPlayersNeededToStart``
4 x ``bool``          ``friendlyFireWithMines``, ``teamVoteOnly``, ``noVehicles`` (``sv.noVehicles``), +0x3d (always true)
5 x ``int``           ``roundsPerMap``, ``spawnTime``, ``timeLimit``, ``ticketRatio``, ``teamRatioPercent``
2 x ``bool``          ``autoBalanceTeam``, ``useGlobalUnlocks``
3 x ``int``           ``coopBotRatio``, ``coopBotCount``, ``coopBotDifficulty``
====================  ========================================================================

``int`` is a sign bit followed by 31 magnitude bits (negative: sign 1). ``timeLimit`` is in seconds.
Only fields the engine can name are named; the two constant booleans are kept so the stream stays aligned.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .bitstream import BitStream


def _int31(bs: BitStream) -> int:
    negative = bs.read_bits(1) == 1
    value = bs.read_bits(31)
    return -value if negative else value


def _string(bs: BitStream) -> str:
    length = bs.read_bits(16)
    return bytes(bs.read_bits(8) for _ in range(length)).decode("latin1")


def decode_server_info(data: bytes) -> Optional[Dict[str, object]]:
    """Decode the kind 0 block; ``None`` when the block is too short to be one."""
    bs = BitStream(data)
    f: Dict[str, object] = {"server_name": _string(bs)}
    lines: List[str] = [_string(bs) for _ in range(bs.read_bits(16))]
    f["welcome_message"] = lines
    for name in ("response_flag", "voip_server_remote", "allow_nose_cam", "hit_indicator", "tk_punish_by_default",
                 "allow_free_cam", "allow_external_views"):
        f[name] = bs.read_bits(1) == 1
    f["voip_server_address"] = bs.read_bits(32)
    f["voip_server_port"] = bs.read_bits(16)
    f["voip_bf_client_port"] = bs.read_bits(16)
    f["voip_quality"] = _int31(bs)
    f["gamespy_port"] = bs.read_bits(16)
    f["radio_spam_interval"] = _int31(bs)
    f["radio_max_spam_flag_count"] = _int31(bs)
    f["radio_blocked_duration_time"] = _int31(bs)
    f["reserved_36"] = bs.read_bits(1) == 1
    f["voting_enabled"] = bs.read_bits(1) == 1
    f["num_players_needed_to_start"] = bs.read_bits(16)
    for name in ("friendly_fire_with_mines", "team_vote_only", "no_vehicles", "constant_3d"):
        f[name] = bs.read_bits(1) == 1
    for name in ("rounds_per_map", "spawn_time", "time_limit", "ticket_ratio", "team_ratio_percent"):
        f[name] = _int31(bs)
    f["auto_balance_team"] = bs.read_bits(1) == 1
    f["use_global_unlocks"] = bs.read_bits(1) == 1
    for name in ("coop_bot_ratio", "coop_bot_count", "coop_bot_difficulty"):
        f[name] = _int31(bs)
    return None if bs.overrun else f


def decode_map_info(data: bytes) -> Optional[Dict[str, object]]:
    """The kind 2 block (``MapInfo::setFromDataBlock`` 0x0805f810): game mode, level path, level name, then
    ``int`` max players (``getMaxNumberOfPlayers``), ``bool`` commander enabled (``getCommanderEnabled``), ``int`` challenge ordinal
    (``getChallengeOrdinal``) and two ``bool`` the engine never names (+0x18, +0x19)."""
    bs = BitStream(data)
    f: Dict[str, object] = {"game_mode": _string(bs), "level_path": _string(bs), "level": _string(bs)}
    f["max_players"] = _int31(bs)
    f["commander_enabled"] = bs.read_bits(1) == 1
    f["challenge_ordinal"] = _int31(bs)
    f["flag_18"] = bs.read_bits(1) == 1
    f["flag_19"] = bs.read_bits(1) == 1
    return None if bs.overrun else f
