"""Comparable company analysis - PE/PB/PS sector comparison."""

import logging

from stock_agents.data.data_manager import DataManager

logger = logging.getLogger(__name__)

# Common sector peer groups for A-shares
SECTOR_PEERS = {
    "600519": ["000858", "000568", "002304", "603369"],  # 白酒
    "000858": ["600519", "000568", "002304", "603369"],  # 白酒
    "601318": ["601628", "601336", "600036", "601166"],  # 金融
    "600036": ["601166", "601398", "601288", "601328"],  # 银行
    "000001": ["600036", "601166", "601398", "601288"],  # 银行
}


def get_comparable_analysis(symbol: str, data: DataManager, peers: list[str] | None = None) -> dict:
    """Compare PE/PB/PS ratios with sector peers."""
    if peers is None:
        peers = SECTOR_PEERS.get(symbol, [])

    if not peers:
        return {"note": "No peers configured for this stock"}

    try:
        target = data.get_stock_snapshot(symbol)
        peer_data = []
        for peer_sym in peers[:5]:
            try:
                snap = data.get_stock_snapshot(peer_sym)
                peer_data.append({
                    "symbol": peer_sym,
                    "name": snap.name,
                    "pe": snap.pe_ratio,
                    "pb": snap.pb_ratio,
                    "market_cap": snap.market_cap,
                })
            except Exception:
                continue

        if not peer_data:
            return {"note": "Could not fetch peer data"}

        # Calculate sector averages
        pe_vals = [p["pe"] for p in peer_data if p["pe"] and p["pe"] > 0]
        pb_vals = [p["pb"] for p in peer_data if p["pb"] and p["pb"] > 0]

        avg_pe = sum(pe_vals) / len(pe_vals) if pe_vals else None
        avg_pb = sum(pb_vals) / len(pb_vals) if pb_vals else None

        pe_premium = None
        if target.pe_ratio and avg_pe:
            pe_premium = (target.pe_ratio - avg_pe) / avg_pe * 100

        pb_premium = None
        if target.pb_ratio and avg_pb:
            pb_premium = (target.pb_ratio - avg_pb) / avg_pb * 100

        return {
            "target": {
                "symbol": symbol,
                "name": target.name,
                "pe": target.pe_ratio,
                "pb": target.pb_ratio,
            },
            "sector_avg_pe": round(avg_pe, 2) if avg_pe else None,
            "sector_avg_pb": round(avg_pb, 2) if avg_pb else None,
            "pe_premium_pct": round(pe_premium, 1) if pe_premium else None,
            "pb_premium_pct": round(pb_premium, 1) if pb_premium else None,
            "peers": peer_data,
        }
    except Exception as e:
        logger.error("Comparable analysis failed: %s", e)
        return {"error": str(e)}
