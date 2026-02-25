import typer
from kcd_gfx_toolbox import cli_extract, cli_normalize, cli_diff

app = typer.Typer(
    help="A toolbox for extracting, normalizing and diffing Scaleform GFx files (used by Kingdom Come: Deliverance).",
    no_args_is_help=True,
)

app.command("extract", no_args_is_help=True)(cli_extract.command)
app.command("normalize", no_args_is_help=True)(cli_normalize.command)
app.command("diff", no_args_is_help=True)(cli_diff.command)


if __name__ == "__main__":
    app()
