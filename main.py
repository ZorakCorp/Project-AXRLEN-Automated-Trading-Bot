import argparse
import logging
import os

from ai_model import PredictionModel
from config import MODEL_PATH
from trading_bot import HyperliquidClient, TradeManager
from data_loader import load_csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def train(args):
    csv_path = args.csv
    if not csv_path:
        raise ValueError("Please pass --csv with historical candle data to train the model")

    df = load_csv(csv_path)
    model = PredictionModel(model_path=MODEL_PATH)
    model.train(df)
    model.save()
    logger.info("Training finished. Saved model to %s", MODEL_PATH)


def run(_: argparse.Namespace):
    client = HyperliquidClient()
    client.validate_tradable_symbol()
    bot = TradeManager(client)
    bot.run()


def calibrate(_: argparse.Namespace):
    from datetime import datetime, timezone

    from raw_data_engine import RawDataIngestion
    from state_store import save_json
    from stats_service import iter_pnls_from_journal, summarize_pnl

    journal = os.getenv("BOT_JOURNAL_PATH", "bot_journal.jsonl")
    pnls = list(iter_pnls_from_journal(journal))
    now = datetime.now(timezone.utc)
    summary = summarize_pnl(pnls, now=now, window="month")
    report = {
        "journal_path": journal,
        "pnl_window": "month",
        "summary": summary,
        "trades_in_journal": len(pnls),
    }
    out_path = os.getenv("CALIBRATION_OUT_PATH", "calibration_out.json")

    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY unset; writing report JSON without LLM diagnostic.")
        save_json(out_path, {"report": report, "diagnostic": None})
        logger.info("Calibration report written to %s", out_path)
        return

    engine = RawDataIngestion()
    diagnostic = engine.run_calibration_analysis(report)
    save_json(out_path, {"report": report, "diagnostic": diagnostic})
    logger.info("Calibration diagnostic written to %s", out_path)


def parse_args():
    parser = argparse.ArgumentParser(description="Automated Ethereum Trading Bot")
    sub = parser.add_subparsers(dest="command", required=True)

    train_parser = sub.add_parser("train", help="Train the AI prediction model")
    train_parser.add_argument("--csv", help="Path to historical candle CSV file", required=True)

    sub.add_parser("run", help="Run the trading bot")
    sub.add_parser("calibrate", help="Run calibration analysis on trade logs")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    if args.command == "train":
        train(args)
    elif args.command == "run":
        run(args)
    elif args.command == "calibrate":
        calibrate(args)
