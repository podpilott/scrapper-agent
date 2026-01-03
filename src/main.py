"""CLI entry point for the Google Maps Lead Scraper."""

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from config.settings import settings
from src.pipeline.orchestrator import Pipeline, PipelineResult
from src.utils.logger import setup_logging

console = Console()


@click.group()
@click.version_option(version="0.1.0", prog_name="Google Maps Lead Scraper")
def cli():
    """Google Maps Lead Generation Scraper.

    Scrape Google Maps for business leads, enrich with contact data,
    score for quality, and generate personalized outreach messages.
    """
    pass


@cli.command()
@click.argument("query")
@click.option(
    "--max-results", "-n",
    default=None,
    type=int,
    help=f"Maximum results to scrape (default: {settings.max_results_per_query})",
)
@click.option(
    "--min-score", "-s",
    default=None,
    type=int,
    help=f"Minimum score for qualified leads (default: {settings.min_score_for_outreach})",
)
@click.option(
    "--skip-enrichment",
    is_flag=True,
    help="Skip website enrichment (faster, less data)",
)
@click.option(
    "--skip-outreach",
    is_flag=True,
    help="Skip outreach message generation (no LLM calls)",
)
@click.option(
    "--product-context", "-p",
    default=None,
    help="Description of your product/service for personalized outreach",
)
@click.option(
    "--output-dir", "-o",
    default=None,
    type=click.Path(),
    help="Output directory for CSV/JSON files",
)
@click.option(
    "--headless/--no-headless",
    default=True,
    help="Run browser in headless mode",
)
def scrape(
    query: str,
    max_results: int | None,
    min_score: int | None,
    skip_enrichment: bool,
    skip_outreach: bool,
    product_context: str | None,
    output_dir: str | None,
    headless: bool,
):
    """Scrape Google Maps for businesses matching QUERY.

    Example:
        scraper scrape "coffee shops in Tokyo"
        scraper scrape "restaurants in NYC" -n 30 --skip-outreach
    """
    setup_logging()

    # Update settings if headless option provided
    if not headless:
        settings.headless = False

    console.print(Panel.fit(
        f"[bold blue]Google Maps Lead Scraper[/bold blue]\n\n"
        f"Query: [green]{query}[/green]\n"
        f"Max Results: {max_results if max_results is not None else settings.max_results_per_query}\n"
        f"Min Score: {min_score if min_score is not None else settings.min_score_for_outreach}\n"
        f"Enrichment: {'Disabled' if skip_enrichment else 'Enabled'}\n"
        f"Outreach: {'Disabled' if skip_outreach else 'Enabled'}",
        title="Configuration",
    ))

    # Create progress tracker
    progress_state = {"step": "", "current": 0, "total": 0}

    def progress_callback(step: str, current: int, total: int):
        progress_state["step"] = step
        progress_state["current"] = current
        progress_state["total"] = total

    # Initialize pipeline
    pipeline = Pipeline(
        max_results=max_results,
        min_score=min_score,
        skip_enrichment=skip_enrichment,
        skip_outreach=skip_outreach,
        product_context=product_context,
        output_dir=Path(output_dir) if output_dir else None,
        progress_callback=progress_callback,
    )

    # Run with progress display
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Running pipeline...", total=100)

        async def run_with_progress():
            result = await pipeline.run(query)
            return result

        # Run the async pipeline
        try:
            result = asyncio.run(run_with_progress())
            progress.update(task, completed=100)
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise click.Abort()

    # Display results
    _display_results(result)


def _display_results(result: PipelineResult):
    """Display pipeline results in a nice format."""
    console.print()

    # Summary table
    table = Table(title="Pipeline Results", show_header=True, header_style="bold magenta")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Query", result.query)
    table.add_row("Total Scraped", str(result.total_scraped))
    table.add_row("Total Enriched", str(result.total_enriched))
    table.add_row("Total Qualified", str(result.total_qualified))
    table.add_row("Total with Outreach", str(result.total_with_outreach))

    if result.duration_seconds:
        table.add_row("Duration", f"{result.duration_seconds:.1f}s")

    console.print(table)

    # Tier breakdown
    if result.leads:
        tiers = {"hot": 0, "warm": 0, "cold": 0}
        for lead in result.leads:
            tiers[lead.tier] = tiers.get(lead.tier, 0) + 1

        tier_table = Table(title="Quality Breakdown", show_header=True)
        tier_table.add_column("Tier", style="bold")
        tier_table.add_column("Count")
        tier_table.add_column("Percentage")

        total = len(result.leads)
        for tier, count in tiers.items():
            color = {"hot": "red", "warm": "yellow", "cold": "blue"}[tier]
            pct = f"{(count/total)*100:.0f}%" if total > 0 else "0%"
            tier_table.add_row(f"[{color}]{tier.upper()}[/{color}]", str(count), pct)

        console.print(tier_table)

    # Top leads preview
    if result.leads:
        console.print("\n[bold]Top 5 Leads:[/bold]")
        for i, lead in enumerate(sorted(result.leads, key=lambda x: x.score, reverse=True)[:5]):
            tier_color = {"hot": "red", "warm": "yellow", "cold": "blue"}[lead.tier]
            console.print(
                f"  {i+1}. [bold]{lead.name}[/bold] "
                f"([{tier_color}]{lead.tier.upper()}[/{tier_color}], Score: {lead.score:.0f})"
            )
            if lead.email:
                console.print(f"     Email: {lead.email}")
            if lead.phone:
                console.print(f"     Phone: {lead.phone}")

    # Output files
    console.print()
    if result.csv_path:
        console.print(f"[green]CSV:[/green] {result.csv_path}")
    if result.json_path:
        console.print(f"[green]JSON:[/green] {result.json_path}")

    console.print("\n[bold green]Done![/bold green]")


@cli.command()
def config():
    """Show current configuration."""
    table = Table(title="Current Configuration", show_header=True)
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    for key, value in settings.model_dump().items():
        # Hide sensitive values
        if "key" in key.lower() or "secret" in key.lower():
            value = "***" if value else "Not set"
        table.add_row(key, str(value))

    console.print(table)


@cli.command()
def init():
    """Initialize the project (install Playwright browsers)."""
    import subprocess

    console.print("[cyan]Installing Playwright browsers...[/cyan]")
    result = subprocess.run(
        ["playwright", "install", "chromium"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        console.print("[green]Playwright browsers installed successfully![/green]")
    else:
        console.print(f"[red]Failed to install browsers: {result.stderr}[/red]")


@cli.command()
@click.option(
    "--host", "-h",
    default=None,
    help="Host to bind to (default: 0.0.0.0)",
)
@click.option(
    "--port", "-p",
    default=None,
    type=int,
    help="Port to bind to (default: 8000)",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development",
)
def serve(host: str | None, port: int | None, reload: bool):
    """Start the API server.

    Example:
        scraper serve
        scraper serve --host 0.0.0.0 --port 8080 --reload
    """
    import uvicorn

    from config.settings import settings

    api_host = host or settings.api_host
    api_port = port or settings.api_port

    console.print(Panel.fit(
        f"[bold blue]Lead Scraper API Server[/bold blue]\n\n"
        f"Host: [green]{api_host}[/green]\n"
        f"Port: [green]{api_port}[/green]\n"
        f"Reload: {'Enabled' if reload else 'Disabled'}\n"
        f"Docs: [cyan]http://{api_host}:{api_port}/docs[/cyan]",
        title="Starting API Server",
    ))

    uvicorn.run(
        "src.api.app:app",
        host=api_host,
        port=api_port,
        reload=reload,
    )


if __name__ == "__main__":
    cli()
