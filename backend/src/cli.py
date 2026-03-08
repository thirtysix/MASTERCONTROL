"""MASTER_CONTROL CLI — masterctl command."""
from __future__ import annotations

import json
import subprocess

import click
from sqlmodel import Session, select

from src.config import settings
from src.db.database import engine, init_db
from src.db.models import Project
from src.services.project_scanner import scan_all


@click.group()
def cli():
    """MASTER CONTROL — Multi-project management CLI."""
    init_db()


@cli.command()
def status():
    """List all projects with status summary."""
    with Session(engine) as session:
        projects = session.exec(select(Project).order_by(Project.name)).all()
        if not projects:
            click.echo("No projects found. Run 'masterctl scan' first.")
            return
        for p in projects:
            tags = json.loads(p.tags)
            tag_str = ", ".join(tags[:3])
            git = f"[{p.git_branch}]" if p.git_branch else ""
            dirty = " *" if p.git_dirty else ""
            docker = f" docker:{p.docker_status}" if p.docker_status else ""
            click.echo(f"  {p.status:<8} {p.name:<30} [{tag_str}] {git}{dirty}{docker}")


@cli.command()
def scan():
    """Re-scan all projects from filesystem."""
    with Session(engine) as session:
        projects = scan_all(session)
        click.echo(f"Scanned {len(projects)} projects.")


@cli.command()
@click.argument("project")
def open(project: str):
    """Open a terminal at a project directory."""
    with Session(engine) as session:
        p = session.get(Project, project)
        if not p:
            # Try partial match
            projects = session.exec(
                select(Project).where(Project.id.contains(project))
            ).all()
            if len(projects) == 1:
                p = projects[0]
            elif len(projects) > 1:
                click.echo("Ambiguous project name. Matches:")
                for proj in projects:
                    click.echo(f"  {proj.id}")
                return
            else:
                click.echo(f"Project '{project}' not found.")
                return
        click.echo(f"Opening terminal at {p.path}")
        subprocess.Popen(
            [settings.terminal_cmd, "--working-directory", p.path],
            start_new_session=True,
        )


@cli.group()
def tag():
    """Manage project tags."""
    pass


@tag.command("add")
@click.argument("project")
@click.argument("tag_name")
def tag_add(project: str, tag_name: str):
    """Add a tag to a project."""
    with Session(engine) as session:
        p = session.get(Project, project)
        if not p:
            click.echo(f"Project '{project}' not found.")
            return
        tags = json.loads(p.tags)
        if tag_name not in tags:
            tags.append(tag_name)
            p.tags = json.dumps(tags)
            session.add(p)
            session.commit()
            click.echo(f"Added tag '{tag_name}' to {project}. Tags: {tags}")
        else:
            click.echo(f"Tag '{tag_name}' already exists on {project}.")


@tag.command("remove")
@click.argument("project")
@click.argument("tag_name")
def tag_remove(project: str, tag_name: str):
    """Remove a tag from a project."""
    with Session(engine) as session:
        p = session.get(Project, project)
        if not p:
            click.echo(f"Project '{project}' not found.")
            return
        tags = json.loads(p.tags)
        if tag_name in tags:
            tags.remove(tag_name)
            p.tags = json.dumps(tags)
            session.add(p)
            session.commit()
            click.echo(f"Removed tag '{tag_name}' from {project}. Tags: {tags}")
        else:
            click.echo(f"Tag '{tag_name}' not found on {project}.")


@tag.command("list")
def tag_list():
    """Show all tags with project counts."""
    with Session(engine) as session:
        projects = session.exec(select(Project)).all()
        tag_counts: dict[str, int] = {}
        for p in projects:
            for t in json.loads(p.tags):
                tag_counts[t] = tag_counts.get(t, 0) + 1
        for t, count in sorted(tag_counts.items(), key=lambda x: -x[1]):
            click.echo(f"  {t:<20} {count} projects")


@cli.command()
@click.argument("tag_name")
def filter(tag_name: str):
    """List projects matching a tag."""
    with Session(engine) as session:
        projects = session.exec(select(Project)).all()
        matches = [p for p in projects if tag_name in json.loads(p.tags)]
        if not matches:
            click.echo(f"No projects with tag '{tag_name}'.")
            return
        click.echo(f"Projects tagged '{tag_name}':")
        for p in matches:
            click.echo(f"  {p.id:<30} {p.name}")


if __name__ == "__main__":
    cli()
