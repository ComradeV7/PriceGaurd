"""Command-line entry points for PriceGuard."""

import logging
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import typer

from priceguard.config import Config
from priceguard.ingest.cache import ReferenceDataCache
from priceguard.ingest.fred import fetch_all_fred_series
from priceguard.ingest.fx import fetch_all_fx_pairs
from priceguard.ingest.stooq import fetch_stooq_prices
from priceguard.ingest.yahoo import fetch_yahoo_prices

app = typer.Typer(help="Synthetic position mark validation and exception reporting.")
logger = logging.getLogger(__name__)


def _placeholder(name: str) -> Callable[[], None]:
    """Create a placeholder command handler."""

    def command() -> None:
        typer.echo(f"{name} is not implemented yet.")

    return command


@app.command()
def ingest(
    offline: bool = typer.Option(
        False, "--offline", help="Use sample data instead of fetching"
    ),
    force_refresh: bool = typer.Option(
        False, "--force-refresh", help="Bypass cache and fetch fresh data"
    ),
    config_dir: Path = typer.Option(
        Path("config"), "--config-dir", help="Configuration directory"
    ),
) -> None:
    """Ingest and cache independent reference data."""
    if offline:
        typer.echo("Offline mode: using sample data")
        _print_sample_coverage(config_dir)
        return

    config = Config.load(config_dir)
    cache_dir = Path(config.settings.paths.data_raw)
    cache = ReferenceDataCache(cache_dir)

    end_date = date.today()
    start_date = end_date - timedelta(days=config.settings.lookback_business_days * 2)

    typer.echo(f"Fetching reference data from {start_date} to {end_date}")
    typer.echo("=" * 80)

    all_data = []

    for instrument in config.universe.instruments:
        try:
            if instrument.ref_source == "yahoo":
                df = fetch_yahoo_prices(
                    instrument.ticker, start_date, end_date, cache, force_refresh
                )
                all_data.append(df)
            elif instrument.ref_source == "fred":
                pass
            elif instrument.ref_source == "fx":
                pass
            elif instrument.ref_source == "stooq" and instrument.stooq_symbol:
                df = fetch_stooq_prices(
                    instrument.ticker,
                    instrument.stooq_symbol,
                    start_date,
                    end_date,
                    cache,
                    force_refresh,
                )
                all_data.append(df)
        except Exception as e:
            logger.error(f"Failed to fetch {instrument.ticker}: {e}")

    fred_df = fetch_all_fred_series(start_date, end_date, cache, force_refresh)
    all_data.append(fred_df)

    fx_df = fetch_all_fx_pairs(start_date, end_date, cache, force_refresh)
    all_data.append(fx_df)

    combined = pd.concat(all_data, ignore_index=True)
    _print_coverage_summary(combined, start_date, end_date)


def _print_sample_coverage(config_dir: Path) -> None:
    """Print coverage summary for sample data."""
    config = Config.load(config_dir)
    sample_dir = Path(config.settings.paths.data_sample)

    if not sample_dir.exists():
        typer.echo("No sample data available")
        return

    parquet_files = list(sample_dir.glob("*.parquet"))
    if not parquet_files:
        typer.echo("No sample data files found")
        return

    all_data = []
    for pf in parquet_files:
        df = pd.read_parquet(pf)
        all_data.append(df)

    if all_data:
        combined = pd.concat(all_data, ignore_index=True)
        end_date = date.today()
        start_date = end_date - timedelta(days=180)
        _print_coverage_summary(combined, start_date, end_date)


def _print_coverage_summary(df: pd.DataFrame, start_date: date, end_date: date) -> None:
    """Print coverage summary for fetched data."""
    if df.empty:
        typer.echo("No data fetched")
        return

    typer.echo("\nCoverage Summary:")
    typer.echo("-" * 80)
    typer.echo(f"{'Symbol':<20} {'First Date':<12} {'Last Date':<12} {'Records':<10}")
    typer.echo("-" * 80)

    for symbol in sorted(df["symbol"].unique()):
        symbol_df = df[df["symbol"] == symbol]
        if symbol_df.empty:
            continue

        first_date = symbol_df["price_date"].min().strftime("%Y-%m-%d")
        last_date = symbol_df["price_date"].max().strftime("%Y-%m-%d")
        count = len(symbol_df)

        typer.echo(f"{symbol:<20} {first_date:<12} {last_date:<12} {count:<10}")

    typer.echo("-" * 80)
    typer.echo(f"Total records: {len(df)}")


@app.command()
def generate(
    offline: bool = typer.Option(
        False, "--offline", help="Use sample data instead of the raw cache"
    ),
    config_dir: Path = typer.Option(
        Path("config"), "--config-dir", help="Configuration directory"
    ),
) -> None:
    """Generate the synthetic portfolio, clean marks and injected faults."""
    from priceguard.db.repo import Repository
    from priceguard.ingest.cache import load_all_cached
    from priceguard.pricing.bond_pricer import price_bond_series
    from priceguard.synth.faults import inject_faults
    from priceguard.synth.marks import generate_clean_marks
    from priceguard.synth.portfolio import (
        generate_portfolio,
        instruments_frame,
        l3_models_frame,
    )

    config = Config.load(config_dir)
    data_dir = (
        Path(config.settings.paths.data_sample)
        if offline
        else Path(config.settings.paths.data_raw)
    )
    if not data_dir.exists():
        typer.echo(f"Data directory not found: {data_dir}")
        raise typer.Exit(code=1)

    raw = load_all_cached(data_dir)
    if raw.empty:
        typer.echo(f"No reference data found in {data_dir}. Run ingest first.")
        raise typer.Exit(code=1)

    raw["price_date"] = pd.to_datetime(raw["price_date"])

    yc = config.settings.yield_curve
    tenor_map = dict(zip(yc.fred_series, yc.tenors_years))
    fred_rows = raw[raw["source"] == "fred"]

    bond_frames = []
    for instrument in config.universe.instruments:
        if instrument.asset_class != "bond_l2":
            continue
        if instrument.maturity_date is None or instrument.coupon is None:
            typer.echo(f"Bond {instrument.ticker} missing coupon/maturity_date")
            continue
        try:
            series = price_bond_series(
                face_value=100.0,
                coupon_rate=instrument.coupon,
                maturity_date=instrument.maturity_date,
                yield_series=fred_rows.rename(columns={"symbol": "symbol"}),
                tenor_map=tenor_map,
            )
        except ValueError as e:
            typer.echo(f"Skipping {instrument.ticker}: {e}")
            continue
        bond_frames.append(
            pd.DataFrame(
                {
                    "symbol": instrument.ticker,
                    "price_date": series["price_date"],
                    "price": series["price"],
                    "source": "fred_model",
                }
            )
        )

    reference_prices = pd.concat(
        [raw[raw["source"] != "fred"]] + bond_frames, ignore_index=True
    )

    instruments = instruments_frame(config)
    positions = generate_portfolio(config)
    l3_models = l3_models_frame(config)

    clean_marks = generate_clean_marks(
        positions=positions,
        instruments=instruments,
        reference_prices=reference_prices,
        l3_models=l3_models,
        config=config,
    )
    usdinr = raw[raw["symbol"] == "USDINR"]
    faulty_marks, ground_truth = inject_faults(
        marks=clean_marks,
        positions=positions,
        instruments=instruments,
        fx_rates=usdinr,
        config=config,
    )

    db_path = Path(config.settings.paths.db)
    with Repository(db_path) as repo:
        repo.insert_dataframe("instruments", instruments)
        repo.insert_dataframe("positions", positions)
        repo.insert_dataframe("l3_models", l3_models)

        ref_db = reference_prices.rename(columns={"symbol": "instrument_id"})[
            ["instrument_id", "price_date", "price", "source"]
        ].copy()
        ref_db["price_date"] = pd.to_datetime(ref_db["price_date"]).dt.date.astype(str)
        repo.insert_dataframe("reference_prices", ref_db)

        marks_db = faulty_marks.copy()
        marks_db["mark_date"] = pd.to_datetime(marks_db["mark_date"]).dt.date.astype(
            str
        )
        repo.insert_dataframe("internal_marks", marks_db)

        gt_db = ground_truth.copy()
        if not gt_db.empty:
            gt_db["mark_date"] = pd.to_datetime(gt_db["mark_date"]).dt.date.astype(str)
        repo.insert_dataframe("ground_truth", gt_db)

    typer.echo(f"Generated {len(positions)} positions, {len(marks_db)} marks")
    typer.echo(
        f"Injected {len(gt_db)} ground-truth fault rows "
        f"({gt_db['fault_type'].nunique() if not gt_db.empty else 0} types)"
    )
    typer.echo(f"Persisted to {db_path}")


@app.command()
def validate(
    mark_date: str = typer.Option(
        None, "--mark-date", help="Single date to validate (YYYY-MM-DD)"
    ),
    start_date: str = typer.Option(
        None, "--start-date", help="Range start (YYYY-MM-DD)"
    ),
    end_date: str = typer.Option(None, "--end-date", help="Range end (YYYY-MM-DD)"),
    config_dir: Path = typer.Option(
        Path("config"), "--config-dir", help="Configuration directory"
    ),
) -> None:
    """Validate internal marks against reference prices."""
    from priceguard.commentary.guardrails import draft_and_store
    from priceguard.commentary.template_provider import TemplateProvider
    from priceguard.db.repo import Repository
    from priceguard.validation.engine import run_validation

    config = Config.load(config_dir)
    db_path = Path(config.settings.paths.db)
    if not db_path.exists():
        typer.echo(f"Database not found: {db_path}. Run generate first.")
        raise typer.Exit(code=1)

    parsed_mark = date.fromisoformat(mark_date) if mark_date is not None else None
    parsed_start = date.fromisoformat(start_date) if start_date is not None else None
    parsed_end = date.fromisoformat(end_date) if end_date is not None else None

    with Repository(db_path) as repo:
        exceptions = run_validation(
            repo,
            config,
            config_dir,
            mark_date=parsed_mark,
            start_date=parsed_start,
            end_date=parsed_end,
        )
        provider = TemplateProvider()
        for row in exceptions.to_dict(orient="records"):
            facts = {
                key: row.get(key)
                for key in (
                    "exception_id",
                    "position_id",
                    "mark_date",
                    "check_name",
                    "severity",
                    "mark",
                    "reference_price",
                    "deviation_bps",
                    "mv_impact_usd",
                    "suspected_cause",
                )
            }
            draft_and_store(repo, row["exception_id"], facts, provider)

    if exceptions.empty:
        typer.echo("No exceptions found.")
        return

    typer.echo(f"Wrote {len(exceptions)} exceptions:")
    counts = exceptions.groupby("severity")["exception_id"].count()
    for severity, count in counts.items():
        typer.echo(f"  {severity}: {count}")


@app.command()
def backtest(
    config_dir: Path = typer.Option(Path("config"), "--config-dir"),
    output_dir: Path = typer.Option(Path("exports"), "--output-dir"),
) -> None:
    """Measure detection against synthetic ground truth."""
    from priceguard.backtest.metrics import metrics_from_repository
    from priceguard.backtest.report import write_report
    from priceguard.db.repo import Repository

    config = Config.load(config_dir)
    db_path = Path(config.settings.paths.db)
    if not db_path.exists():
        typer.echo(f"Database not found: {db_path}. Run generate and validate first.")
        raise typer.Exit(code=1)
    with Repository(db_path) as repo:
        metrics = metrics_from_repository(repo)
    csv_path, report_path = write_report(metrics, output_dir)
    typer.echo(
        pd.DataFrame(
            [
                {
                    "recall": metrics["recall"],
                    "precision": metrics["precision"],
                    "false_positive_rate": metrics["false_positive_rate"],
                }
            ]
        ).to_string(index=False)
    )
    if not metrics["per_fault_type"].empty:
        typer.echo(metrics["per_fault_type"].to_string(index=False))
    typer.echo(f"Wrote {csv_path} and {report_path}")


@app.command(name="export")
def export_data(
    config_dir: Path = typer.Option(Path("config"), "--config-dir"),
    output_dir: Path = typer.Option(Path("exports"), "--output-dir"),
    mark_date: str = typer.Option(None, "--mark-date"),
) -> None:
    """Export review and reporting data."""
    from priceguard.db.repo import Repository
    from priceguard.export.excel_input import export_daily_exceptions
    from priceguard.export.powerbi import export_powerbi

    config = Config.load(config_dir)
    db_path = Path(config.settings.paths.db)
    if not db_path.exists():
        typer.echo(f"Database not found: {db_path}. Run generate first.")
        raise typer.Exit(code=1)
    selected_date = date.fromisoformat(mark_date) if mark_date else None
    with Repository(db_path) as repo:
        csv_path, xlsx_path = export_daily_exceptions(repo, output_dir, selected_date)
        paths = export_powerbi(repo, output_dir / "powerbi")
    typer.echo(f"Wrote {csv_path}")
    typer.echo(f"Wrote {xlsx_path}")
    typer.echo(f"Wrote {len(paths)} Power BI files to {output_dir / 'powerbi'}")


@app.command()
def review(
    exception_id: str = typer.Option(None, "--exception-id"),
    action: str = typer.Option(
        "list", "--action", help="list/show/approve/edit/status/note/ingest-csv"
    ),
    reviewer: str = typer.Option(None, "--reviewer"),
    status: str = typer.Option(None, "--status"),
    note: str = typer.Option(None, "--note"),
    text: str = typer.Option(None, "--text"),
    csv_path: Path = typer.Option(None, "--csv-path"),
    config_dir: Path = typer.Option(Path("config"), "--config-dir"),
) -> None:
    """Process the human review queue."""
    from priceguard.db.repo import Repository
    from priceguard.review.queue import (
        add_note,
        approve_draft,
        edit_draft,
        exception_facts,
        ingest_reviewed_csv,
        list_open_exceptions,
        set_status,
    )

    config = Config.load(config_dir)
    db_path = Path(config.settings.paths.db)
    if not db_path.exists():
        typer.echo(f"Database not found: {db_path}. Run generate and validate first.")
        raise typer.Exit(code=1)
    with Repository(db_path) as repo:
        if action == "list":
            typer.echo(list_open_exceptions(repo).to_string(index=False))
        elif action == "show":
            if not exception_id:
                raise typer.BadParameter("--exception-id is required")
            typer.echo(pd.Series(exception_facts(repo, exception_id)).to_string())
        elif action == "approve":
            approve_draft(repo, exception_id, reviewer)
        elif action == "edit":
            edit_draft(repo, exception_id, reviewer, text or "")
        elif action == "status":
            set_status(repo, exception_id, status or "", reviewer, note)
        elif action == "note":
            add_note(repo, exception_id, reviewer, note or "")
        elif action == "ingest-csv":
            if not csv_path:
                raise typer.BadParameter("--csv-path is required")
            result = ingest_reviewed_csv(repo, csv_path, reviewer)
            typer.echo(f"Applied: {result['applied']}")
            typer.echo(result["invalid"].to_string(index=False))
        else:
            raise typer.BadParameter(f"unknown review action: {action}")


@app.command(name="run-all")
def run_all(
    offline: bool = typer.Option(
        False, "--offline", help="Use sample data instead of fetching"
    ),
    seed: int = typer.Option(42, "--seed", help="Random seed for reproducibility"),
    start_date: str = typer.Option(
        None, "--start-date", help="Start date (YYYY-MM-DD)"
    ),
    end_date: str = typer.Option(None, "--end-date", help="End date (YYYY-MM-DD)"),
    skip_llm: bool = typer.Option(
        True, "--skip-llm", help="Skip LLM commentary (use templates only)"
    ),
    simulate_workflow: bool = typer.Option(
        False, "--simulate-workflow", help="Run workflow simulation"
    ),
    config_dir: Path = typer.Option(
        Path("config"), "--config-dir", help="Configuration directory"
    ),
    output_dir: Path = typer.Option(
        Path("exports"), "--output-dir", help="Output directory"
    ),
) -> None:
    """Run the complete pipeline: ingest -> generate -> validate -> backtest -> export.

    This command executes all pipeline stages in sequence with progress output
    and a final summary table. Each step is idempotent and can be re-run safely.
    """
    import time

    from priceguard.backtest.metrics import metrics_from_repository
    from priceguard.backtest.report import write_report
    from priceguard.commentary.guardrails import draft_and_store
    from priceguard.commentary.template_provider import TemplateProvider
    from priceguard.db.repo import Repository
    from priceguard.export.excel_input import export_daily_exceptions
    from priceguard.export.powerbi import export_powerbi
    from priceguard.validation.engine import run_validation
    from priceguard.workflow.simulate import simulate_workflow as run_simulation

    # Set up logging
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"run_all_{date.today():%Y%m%d_%H%M%S}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )

    start_time = time.time()
    results = {}

    typer.echo("=" * 80)
    typer.echo("PriceGuard Pipeline - Run All")
    typer.echo("=" * 80)
    typer.echo(f"Mode: {'Offline' if offline else 'Online'}")
    typer.echo(f"Seed: {seed}")
    typer.echo(f"Config: {config_dir}")
    typer.echo(f"Output: {output_dir}")
    typer.echo(f"Log file: {log_file}")
    typer.echo("=" * 80)

    try:
        config = Config.load(config_dir)
        # Override seed if provided
        config.settings.seed = seed
    except Exception as e:
        typer.echo(f"Error loading config: {e}", err=True)
        raise typer.Exit(code=1)

    # Step 1: Ingest
    typer.echo("\n[1/6] Ingesting reference data...")
    step_start = time.time()
    try:
        if offline:
            typer.echo("  Using sample data (offline mode)")
            results["ingest"] = "Skipped (offline)"
        else:
            # Call ingest logic
            cache_dir = Path(config.settings.paths.data_raw)
            cache = ReferenceDataCache(cache_dir)
            end_dt = date.fromisoformat(end_date) if end_date else date.today()
            lookback = config.settings.lookback_business_days * 2
            start_dt = (
                date.fromisoformat(start_date)
                if start_date
                else end_dt - timedelta(days=lookback)
            )

            all_data = []
            for instrument in config.universe.instruments:
                try:
                    if instrument.ref_source == "yahoo":
                        df = fetch_yahoo_prices(
                            instrument.ticker, start_dt, end_dt, cache, False
                        )
                        all_data.append(df)
                    elif instrument.ref_source == "stooq" and instrument.stooq_symbol:
                        df = fetch_stooq_prices(
                            instrument.ticker,
                            instrument.stooq_symbol,
                            start_dt,
                            end_dt,
                            cache,
                            False,
                        )
                        all_data.append(df)
                except Exception as e:
                    logger.warning(f"Failed to fetch {instrument.ticker}: {e}")

            fred_df = fetch_all_fred_series(start_dt, end_dt, cache, False)
            all_data.append(fred_df)

            fx_df = fetch_all_fx_pairs(start_dt, end_dt, cache, False)
            all_data.append(fx_df)

            combined = pd.concat(all_data, ignore_index=True)
            results["ingest"] = f"OK ({len(combined)} records)"
            typer.echo(f"  Ingested {len(combined)} reference records")
    except Exception as e:
        logger.error(f"Ingest failed: {e}")
        results["ingest"] = f"FAILED: {e}"
    step_time = time.time() - step_start
    typer.echo(f"  Completed in {step_time:.2f}s")

    # Step 2: Generate
    typer.echo("\n[2/6] Generating portfolio and marks...")
    step_start = time.time()
    try:
        from priceguard.ingest.cache import load_all_cached
        from priceguard.pricing.bond_pricer import price_bond_series
        from priceguard.synth.faults import inject_faults
        from priceguard.synth.marks import generate_clean_marks
        from priceguard.synth.portfolio import (
            generate_portfolio,
            instruments_frame,
            l3_models_frame,
        )

        data_dir = (
            Path(config.settings.paths.data_sample)
            if offline
            else Path(config.settings.paths.data_raw)
        )
        raw = load_all_cached(data_dir)

        if raw.empty:
            raise ValueError(f"No reference data found in {data_dir}")

        raw["price_date"] = pd.to_datetime(raw["price_date"])

        # Price bonds
        yc = config.settings.yield_curve
        tenor_map = dict(zip(yc.fred_series, yc.tenors_years))
        fred_rows = raw[raw["source"] == "fred"]

        bond_frames = []
        for instrument in config.universe.instruments:
            if instrument.asset_class != "bond_l2":
                continue
            if instrument.maturity_date is None or instrument.coupon is None:
                continue
            try:
                series = price_bond_series(
                    face_value=100.0,
                    coupon_rate=instrument.coupon,
                    maturity_date=instrument.maturity_date,
                    yield_series=fred_rows,
                    tenor_map=tenor_map,
                )
                bond_frames.append(
                    pd.DataFrame(
                        {
                            "symbol": instrument.ticker,
                            "price_date": series["price_date"],
                            "price": series["price"],
                            "source": "fred_model",
                        }
                    )
                )
            except Exception as e:
                logger.warning(f"Failed to price {instrument.ticker}: {e}")

        reference_prices = pd.concat(
            [raw[raw["source"] != "fred"]] + bond_frames, ignore_index=True
        )

        instruments = instruments_frame(config)
        positions = generate_portfolio(config)
        l3_models = l3_models_frame(config)

        clean_marks = generate_clean_marks(
            positions, instruments, reference_prices, l3_models, config
        )
        usdinr = raw[raw["symbol"] == "USDINR"]
        faulty_marks, ground_truth = inject_faults(
            clean_marks, positions, instruments, usdinr, config
        )

        db_path = Path(config.settings.paths.db)
        with Repository(db_path) as repo:
            repo.insert_dataframe("instruments", instruments)
            repo.insert_dataframe("positions", positions)
            repo.insert_dataframe("l3_models", l3_models)

            ref_db = reference_prices.rename(columns={"symbol": "instrument_id"})[
                ["instrument_id", "price_date", "price", "source"]
            ].copy()
            ref_db["price_date"] = pd.to_datetime(ref_db["price_date"]).dt.date.astype(
                str
            )
            repo.insert_dataframe("reference_prices", ref_db)

            marks_db = faulty_marks.copy()
            marks_db["mark_date"] = pd.to_datetime(
                marks_db["mark_date"]
            ).dt.date.astype(str)
            repo.insert_dataframe("internal_marks", marks_db)

            gt_db = ground_truth.copy()
            if not gt_db.empty:
                gt_db["mark_date"] = pd.to_datetime(gt_db["mark_date"]).dt.date.astype(
                    str
                )
            repo.insert_dataframe("ground_truth", gt_db)

        results["generate"] = (
            f"OK ({len(positions)} positions, {len(marks_db)} marks, "
            f"{len(gt_db)} faults)"
        )
        typer.echo(
            f"  Generated {len(positions)} positions, {len(marks_db)} marks, "
            f"{len(gt_db)} faults"
        )
    except Exception as e:
        logger.error(f"Generate failed: {e}")
        results["generate"] = f"FAILED: {e}"
    step_time = time.time() - step_start
    typer.echo(f"  Completed in {step_time:.2f}s")

    # Step 3: Validate
    typer.echo("\n[3/6] Validating marks...")
    step_start = time.time()
    try:
        parsed_start = date.fromisoformat(start_date) if start_date else None
        parsed_end = date.fromisoformat(end_date) if end_date else None

        with Repository(db_path) as repo:
            exceptions = run_validation(
                repo, config, config_dir, start_date=parsed_start, end_date=parsed_end
            )

            # Generate commentary drafts
            provider = TemplateProvider()
            for row in exceptions.to_dict(orient="records"):
                facts = {
                    key: row.get(key)
                    for key in (
                        "exception_id",
                        "position_id",
                        "mark_date",
                        "check_name",
                        "severity",
                        "mark",
                        "reference_price",
                        "deviation_bps",
                        "mv_impact_usd",
                        "suspected_cause",
                    )
                }
                draft_and_store(repo, row["exception_id"], facts, provider)

        results["validate"] = f"OK ({len(exceptions)} exceptions)"
        typer.echo(f"  Validated and found {len(exceptions)} exceptions")
    except Exception as e:
        logger.error(f"Validate failed: {e}")
        results["validate"] = f"FAILED: {e}"
    step_time = time.time() - step_start
    typer.echo(f"  Completed in {step_time:.2f}s")

    # Step 4: Simulate workflow (optional)
    if simulate_workflow:
        typer.echo("\n[4/6] Simulating workflow...")
        step_start = time.time()
        try:
            with Repository(db_path) as repo:
                changed = run_simulation(repo, seed=seed, fraction=0.35)
            results["simulate"] = f"OK ({changed} exceptions updated)"
            typer.echo(f"  Simulated workflow for {changed} exceptions")
        except Exception as e:
            logger.error(f"Simulate failed: {e}")
            results["simulate"] = f"FAILED: {e}"
        step_time = time.time() - step_start
        typer.echo(f"  Completed in {step_time:.2f}s")
    else:
        typer.echo(
            "\n[4/6] Skipping workflow simulation (use --simulate-workflow to enable)"
        )
        results["simulate"] = "Skipped"

    # Step 5: Backtest
    typer.echo("\n[5/6] Running backtest...")
    step_start = time.time()
    try:
        with Repository(db_path) as repo:
            metrics = metrics_from_repository(repo)
        csv_path, report_path = write_report(metrics, output_dir)
        results["backtest"] = (
            f"OK (recall={metrics['recall']:.2%}, precision={metrics['precision']:.2%})"
        )
        typer.echo(
            f"  Backtest complete: recall={metrics['recall']:.2%}, "
            f"precision={metrics['precision']:.2%}"
        )
        typer.echo(f"  Reports: {csv_path}, {report_path}")
    except Exception as e:
        logger.error(f"Backtest failed: {e}")
        results["backtest"] = f"FAILED: {e}"
    step_time = time.time() - step_start
    typer.echo(f"  Completed in {step_time:.2f}s")

    # Step 6: Export
    typer.echo("\n[6/6] Exporting data...")
    step_start = time.time()
    try:
        with Repository(db_path) as repo:
            csv_path, xlsx_path = export_daily_exceptions(repo, output_dir)
            paths = export_powerbi(repo, output_dir / "powerbi")
        results["export"] = f"OK ({len(paths)} Power BI files)"
        typer.echo(f"  Exported: {csv_path}, {xlsx_path}")
        typer.echo(f"  Power BI files: {len(paths)} files in {output_dir / 'powerbi'}")
    except Exception as e:
        logger.error(f"Export failed: {e}")
        results["export"] = f"FAILED: {e}"
    step_time = time.time() - step_start
    typer.echo(f"  Completed in {step_time:.2f}s")

    # Summary
    total_time = time.time() - start_time
    typer.echo("\n" + "=" * 80)
    typer.echo("Pipeline Summary")
    typer.echo("=" * 80)
    typer.echo(f"Total time: {total_time:.2f}s")
    typer.echo("\nStep Results:")
    for step, result in results.items():
        typer.echo(f"  {step:20s} {result}")
    typer.echo("=" * 80)
    typer.echo(f"Log file: {log_file}")
    typer.echo("=" * 80)


if __name__ == "__main__":
    app()
