#!/usr/bin/env python3
"""
Todoist to Obsidian Exporter

This script exports Todoist tasks to Obsidian-compatible markdown files.
It always includes completed tasks and can filter tasks by completion date.

Usage:
    python todoist-to-obsidian.py [options]

Examples:
    python todoist-to-obsidian.py                                    # Export all tasks
    python todoist-to-obsidian.py --date 2024-01-15                 # Export tasks completed on Jan 15, 2024

Requirements:
    - TODOIST_API_TOKEN environment variable must be set
    - TODOIST_NOTES_FOLDER environment variable must be set
"""

import argparse
import datetime
import difflib
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import structlog
from pydantic import BaseModel, Field
from todoist_api_python.api import TodoistAPI

# Configure structured logging
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO level
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

log: structlog.BoundLogger = structlog.get_logger()


class TodoistTaskFile:
    """Represents a Todoist task file for export."""

    def __init__(self, path: Path):
        """Initialize TodoistTaskFile."""
        self.path = path


class TodoistProject:
    """Represents a Todoist project."""

    def __init__(self, id: str, name: str):
        """Initialize TodoistProject."""
        self.id = id
        self.name = name

    @classmethod
    def from_api_project(cls, project: Any) -> "TodoistProject":
        """Create TodoistProject from API response."""
        if isinstance(project, dict):
            return cls(id=project["id"], name=project["name"])
        return cls(id=project.id, name=project.name)


class TodoistSection:
    """Represents a Todoist section."""

    def __init__(self, id: str, name: str, project_id: str):
        """Initialize TodoistSection."""
        self.id = id
        self.name = name
        self.project_id = project_id

    @classmethod
    def from_api_section(cls, section: Any) -> "TodoistSection":
        """Create TodoistSection from API response."""
        if isinstance(section, dict):
            return cls(
                id=section["id"], name=section["name"], project_id=section["project_id"]
            )
        return cls(id=section.id, name=section.name, project_id=section.project_id)


class TodoistTask(BaseModel):
    """Represents a Todoist task."""

    id: str
    content: str
    description: str = ""
    project_id: str
    section_id: str | None = None
    parent_id: str | None = None
    order: int
    priority: int = 1
    labels: list[str] = Field(default_factory=list)
    due: dict[str, Any] | None = None
    url: str = ""

    is_completed: bool = False
    created_at: str
    completed_date: str | None = None
    creator_id: str = ""
    assignee_id: str | None = None
    assigner_id: str | None = None

    @property
    def due_date(self) -> str | None:
        """Extract due date as string if available."""
        if self.due and "date" in self.due:
            date_value = self.due["date"]
            return str(date_value) if date_value is not None else None
        return None

    @property
    def priority_text(self) -> str:
        """Convert priority number to text."""
        priority_map = {4: "High", 3: "Normal", 2: "Low", 1: "None"}
        return priority_map.get(self.priority, "None")

    @classmethod
    def from_api_task(
        cls,
        api_task: Any,
        is_completed: bool = False,
    ) -> "TodoistTask":
        """Create TodoistTask from the API task object."""
        # Convert due object to dict if present
        due_dict = None
        if api_task.due:
            due_dict = {
                "date": api_task.due.date,
                "string": getattr(api_task.due, "string", ""),
                "datetime": getattr(api_task.due, "datetime", None),
                "is_recurring": getattr(api_task.due, "is_recurring", False),
            }

        return cls(
            id=api_task.id,
            content=api_task.content,
            project_id=api_task.project_id,
            section_id=api_task.section_id,
            parent_id=api_task.parent_id,
            order=api_task.order,
            priority=api_task.priority,
            labels=api_task.labels or [],
            due=due_dict,
            url=api_task.url,
            is_completed=is_completed,
            created_at=str(api_task.created_at),
            completed_date=str(api_task.completed_at),
            creator_id=api_task.creator_id or "",
            assignee_id=api_task.assignee_id,
            assigner_id=api_task.assigner_id,
        )


class TodoistComment(BaseModel):
    """Represents a comment on a Todoist task."""

    id: str
    task_id: str
    content: str
    posted_at: str
    attachment: dict[str, Any] | None = None

    @classmethod
    def from_api_comment(cls, api_comment: Any) -> "TodoistComment":
        """Create TodoistComment from the API comment object."""
        attachment_dict = None
        if hasattr(api_comment, "attachment") and api_comment.attachment:
            attachment_dict = {
                "file_name": getattr(api_comment.attachment, "file_name", None),
                "file_type": getattr(api_comment.attachment, "file_type", None),
                "file_url": getattr(api_comment.attachment, "file_url", None),
                "resource_type": getattr(api_comment.attachment, "resource_type", None),
            }

        return cls(
            id=api_comment.id,
            task_id=api_comment.task_id or "",
            content=api_comment.content,
            posted_at=str(api_comment.posted_at),
            attachment=attachment_dict,
        )


class TodoistAPIError(Exception):
    """Exception raised for Todoist API errors."""

    pass


class TodoistClient:
    """Client for interacting with the Todoist API using todoist-api-python."""

    def __init__(self, token: str):
        """Initialize TodoistClient."""
        self.token = token
        self.api = TodoistAPI(token)

    def get_projects(self) -> list[TodoistProject]:
        """Get all projects."""
        try:
            projects = self.api.get_projects()
            return [
                TodoistProject.from_api_project(p) for page in projects for p in page
            ]
        except Exception as e:
            raise TodoistAPIError(f"Failed to get projects: {e}")

    def get_sections(self) -> list[TodoistSection]:
        """Get all sections."""
        try:
            sections = self.api.get_sections()
            return [
                TodoistSection.from_api_section(s) for page in sections for s in page
            ]
        except Exception as e:
            raise TodoistAPIError(f"Failed to get sections: {e}")

    def get_tasks(
        self, project_id: str | None = None, filter_expr: str | None = None
    ) -> list[TodoistTask]:
        """Get tasks, optionally filtered by project and/or filter expression."""
        try:
            if filter_expr:
                tasks_iter = self.api.filter_tasks(query=filter_expr)
                tasks = [
                    TodoistTask.from_api_task(t) for page in tasks_iter for t in page
                ]
                if project_id:
                    tasks = [t for t in tasks if t.project_id == project_id]
                return tasks

            kwargs = {}
            if project_id:
                kwargs["project_id"] = project_id

            tasks = self.api.get_tasks(**kwargs)
            return [TodoistTask.from_api_task(t) for page in tasks for t in page]
        except Exception as e:
            raise TodoistAPIError(f"Failed to get tasks: {e}")

    def get_task_comments(self, task_id: str) -> list[TodoistComment]:
        """Get comments for a specific task."""
        try:
            comments = self.api.get_comments(task_id=task_id)
            return [
                TodoistComment.from_api_comment(c) for page in comments for c in page
            ]
        except Exception as e:
            # Comments might fail if task is not found or other reasons, just raise for now
            raise TodoistAPIError(f"Failed to get comments for task {task_id}: {e}")

    def get_completed_tasks_by_completion_date(
        self, completion_date: datetime.datetime
    ) -> list[TodoistTask]:
        """Fetch completed tasks for a specific completion date."""
        try:
            start_time = completion_date.replace(hour=0, minute=0)
            end_time = completion_date.replace(hour=23, minute=59)
            completed_items_iterator = self.api.get_completed_tasks_by_completion_date(
                since=start_time, until=end_time
            )
            all_completed_tasks = []
            for items_page in completed_items_iterator:
                for item in items_page:
                    all_completed_tasks.append(
                        TodoistTask.from_api_task(
                            item,
                            is_completed=True,
                        )
                    )
            return all_completed_tasks
        except Exception as e:
            raise TodoistAPIError(
                f"Failed to fetch completed tasks for date {completion_date.isoformat()}: {e}"
            ) from e

    def get_recently_completed_tasks(self, days: int = 7) -> list[TodoistTask]:
        """Fetch recently completed tasks."""
        all_completed_tasks = {}
        try:
            until = datetime.datetime.now()
            since = until - datetime.timedelta(days=days)

            completed_items_iterator = self.api.get_completed_tasks_by_completion_date(
                since=since, until=until
            )

            for items_page in completed_items_iterator:
                for item in items_page:
                    if item.id not in all_completed_tasks:
                        all_completed_tasks[item.id] = TodoistTask.from_api_task(
                            item,
                            is_completed=True,
                        )

            return list(all_completed_tasks.values())
        except Exception as e:
            raise TodoistAPIError(
                f"Failed to fetch recently completed tasks: {e}"
            ) from e

    def get_tasks_by_creation_date(
        self, creation_date: datetime.date
    ) -> list[TodoistTask]:
        """Fetch tasks created on a specific date."""
        try:
            date_str = creation_date.strftime("%Y-%m-%d")
            tasks_iter = self.api.filter_tasks(query=f"created: {date_str}")
            return [TodoistTask.from_api_task(t) for page in tasks_iter for t in page]
        except Exception as e:
            raise TodoistAPIError(
                f"Failed to fetch tasks created on {creation_date.isoformat()}: {e}"
            ) from e


class ExportConfig:
    """Configuration for exporting tasks."""

    def __init__(
        self,
        output_dir: Path,
        include_completed: bool = False,
        include_comments: bool = True,
    ):
        """Initialize ExportConfig."""
        self.output_dir = output_dir
        self.include_completed = include_completed
        self.include_comments = include_comments


class ObsidianExporter:
    """Export Todoist tasks as Obsidian markdown notes."""

    def __init__(self, config: ExportConfig):
        """Initialize the exporter with configuration."""
        self.config = config
        self.output_dir = Path(config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def sanitize_filename(self, name: str) -> str:
        """Sanitize a string for use as a filename."""
        # If the name is a markdown link like [foo](url), keep just the link text
        name = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", name)
        ascii_name = unicodedata.normalize("NFKD", name)
        ascii_name = ascii_name.encode("ascii", "ignore").decode("ascii")
        sanitized = re.sub(r"[\[\]#^|\\/:?]", "_", ascii_name)
        sanitized = re.sub(r"_+", "_", sanitized)
        sanitized = sanitized.strip("_ ")
        if len(sanitized) > 200:
            sanitized = sanitized[:200].rstrip("_")
        return sanitized or "untitled"

    def format_yaml_string(self, value: str) -> str:
        """Format a string value for safe YAML output."""
        if "'" in value and '"' not in value:
            return f'"{value}"'
        if '"' in value and "'" not in value:
            return f"'{value}'"
        if (
            '"' in value
            or "'" in value
            or "\n" in value
            or "\t" in value
            or "\\" in value
        ):
            escaped = value.replace("\\", "\\\\")
            escaped = escaped.replace('"', '\\"')
            escaped = escaped.replace("\n", "\\n")
            escaped = escaped.replace("\t", "\\t")
            return f'"{escaped}"'
        return f'"{value}"'

    def format_tags(self, task: TodoistTask, project: TodoistProject) -> list[str]:
        """Generate tags for a task."""
        tags = []
        tags.append("#todoist")

        project_tag = self.sanitize_filename(project.name.lower().replace(" ", "-"))
        tags.append(f"#todoist/{project_tag}")

        if task.priority > 1:
            priority_name = task.priority_text.lower()
            tags.append(f"#todoist/priority/{priority_name}")

        for label in task.labels:
            label_tag = self.sanitize_filename(label.lower().replace(" ", "-"))
            tags.append(f"#todoist/label/{label_tag}")

        status = "completed" if task.is_completed else "active"
        tags.append(f"#todoist/status/{status}")

        return tags

    def format_frontmatter(
        self,
        task: TodoistTask,
        project: TodoistProject,
        section: TodoistSection | None = None,
    ) -> str:
        """Generate YAML frontmatter for a task."""
        frontmatter = ["---"]
        frontmatter.append("category: task")
        frontmatter.append(f"title: {self.format_yaml_string(task.content)}")
        frontmatter.append(f"todoist_id: {self.format_yaml_string(task.id)}")
        frontmatter.append(f"project: {self.format_yaml_string(project.name)}")
        frontmatter.append(f'project_id: "{project.id}"')

        if section:
            frontmatter.append(f"section: {self.format_yaml_string(section.name)}")
            frontmatter.append(f'section_id: "{section.id}"')

        frontmatter.append(f'created: "{task.created_at[:10]}"')

        if task.due_date:
            frontmatter.append(f'due_date: "{task.due_date}"')

        frontmatter.append(f"priority: {task.priority_text}")

        if task.labels:
            labels_str = '", "'.join(task.labels)
            frontmatter.append(f'labels: ["{labels_str}"]')

        frontmatter.append(f"completed: {str(task.is_completed).lower()}")
        if task.is_completed:
            frontmatter.append("status: done")

        if task.completed_date:
            frontmatter.append(f'completed_date: "{task.completed_date}"')

        if task.url:
            frontmatter.append(f'todoist_url: "{task.url}"')

        tags = self.format_tags(task, project)
        if tags:
            tags_str = '", "'.join(tag.lstrip("#") for tag in tags)
            frontmatter.append(f'tags: ["{tags_str}"]')

        frontmatter.append("---")
        frontmatter.append("")
        return "\n".join(frontmatter)

    def format_task_content(
        self,
        task: TodoistTask,
        project: TodoistProject,
        comments: list[TodoistComment] | None = None,
        child_tasks: list[TodoistTask] | None = None,
        section: TodoistSection | None = None,
    ) -> str:
        """Format a task as markdown content."""
        content = []
        content.append(self.format_frontmatter(task, project, section))

        status_icon = "✅" if task.is_completed else "⬜"
        content.append(f"# {status_icon} {task.content}")
        content.append("")

        if task.description:
            content.append("## Description")
            content.append("")
            content.append(task.description)
            content.append("")

        if child_tasks:
            content.append("## Subtasks")
            content.append("")
            for child_task in sorted(child_tasks, key=lambda t: t.order):
                checkbox = "[x]" if child_task.is_completed else "[ ]"
                content.append(f"- {checkbox} {child_task.content}")
            content.append("")

        if comments and self.config.include_comments:
            content.append("## Comments")
            content.append("")
            for comment in comments:
                dt_object = datetime.datetime.fromisoformat(
                    comment.posted_at.replace("Z", "+00:00")
                )
                formatted_datetime = dt_object.strftime("%d %b %H:%M")
                content.append(f"* {formatted_datetime} - {comment.content}")

        return "\n".join(content)

    def get_output_path(self, task: TodoistTask, project: TodoistProject) -> Path:  # noqa: ARG002
        """Determine the output path for a task note."""
        filename = self.sanitize_filename(task.content)
        return self.output_dir / f"{filename}.md"

    def export_task(
        self,
        task: TodoistTask,
        project: TodoistProject,
        comments: list[TodoistComment] | None = None,
        child_tasks: list[TodoistTask] | None = None,
        section: TodoistSection | None = None,
    ) -> Path:
        """Export a single task as a markdown note."""
        output_path = self.get_output_path(task, project)

        if task.is_completed and not self.config.include_completed:
            return output_path

        # Preserve existing user content after ---
        existing_user_content = ""
        if output_path.exists():
            try:
                with open(output_path, encoding="utf-8") as f:
                    existing_content = f.read()

                lines = existing_content.split("\n")
                separators = []
                for i, line in enumerate(lines):
                    if line.strip() == "---":
                        separators.append(i)

                if len(separators) >= 3:
                    user_content_start = separators[2] + 1
                    user_lines = lines[user_content_start:]
                    if user_lines and any(line.strip() for line in user_lines):
                        existing_user_content = "\n".join(user_lines)
                        if existing_user_content.strip():
                            existing_user_content = (
                                "\n\n---\n\n" + existing_user_content
                            )
            except Exception:
                pass  # Ignore errors reading existing file

        new_content = self.format_task_content(
            task, project, comments, child_tasks, section
        )
        final_content = new_content + existing_user_content

        write_obsidian_file(output_path, final_content)

        return output_path


def parse_date_string(date_str: str) -> datetime.date:
    """
    Parse date string in YYYY-MM-DD format.

    Args:
        date_str: Date string to parse

    Returns:
        Parsed date object

    Raises:
        ValueError: If date format is invalid
    """
    try:
        return datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as err:
        raise ValueError(
            f"Invalid date format: {date_str}. Expected YYYY-MM-DD"
        ) from err


def export_tasks_internal(
    client: TodoistClient,
    export_config: ExportConfig,
    target_date: datetime.date | None = None,
) -> int:
    """Internal function to export tasks."""
    # Get projects
    projects = client.get_projects()
    projects_dict = {p.id: p for p in projects}

    # Get sections
    sections = client.get_sections()
    sections_dict = {s.id: s for s in sections}

    tasks: list[TodoistTask] = []

    if target_date:
        # If a target_date is provided, we fetch completed tasks for that specific date.
        completed_tasks_on_date = client.get_completed_tasks_by_completion_date(
            datetime.datetime.combine(target_date, datetime.time.min)
        )
        tasks.extend(completed_tasks_on_date)

        # Also fetch tasks created on this date
        created_tasks_on_date = client.get_tasks_by_creation_date(target_date)
        seen_ids = {t.id for t in tasks}
        for t in created_tasks_on_date:
            if t.id not in seen_ids:
                tasks.append(t)
    else:
        # If no target_date, proceed with standard task fetching.
        # Get tasks
        tasks = client.get_tasks()

        # Fetch completed tasks (always include completed)
        completed_tasks_general = client.get_recently_completed_tasks(days=7)
        tasks.extend(completed_tasks_general)

    if not tasks:
        return 0

    # Group tasks by parent/child relationship
    parent_tasks = []
    child_tasks_by_parent: dict[str, list[TodoistTask]] = {}

    for task in tasks:
        # Skip tasks that start with *
        if task.content.startswith("*"):
            continue

        if task.parent_id:
            if task.parent_id not in child_tasks_by_parent:
                child_tasks_by_parent[task.parent_id] = []
            child_tasks_by_parent[task.parent_id].append(task)
        else:
            parent_tasks.append(task)

    # Initialize exporter
    exporter = ObsidianExporter(export_config)

    # Export only parent tasks
    exported_count = 0
    for task in parent_tasks:
        project = projects_dict.get(task.project_id)
        if not project:
            continue

        # Get child tasks for this parent
        child_tasks = child_tasks_by_parent.get(task.id, [])

        # Get comments if enabled
        comments = None
        if export_config.include_comments:
            try:
                comments = client.get_task_comments(task.id)
            except TodoistAPIError as e:
                log.warning(
                    f"Failed to fetch comments for task {task.id}: {e}", exc_info=True
                )
                comments = None

        # Get section for this task
        section = sections_dict.get(task.section_id) if task.section_id else None

        # Export the task with its child tasks
        try:
            exporter.export_task(task, project, comments, child_tasks, section)
            exported_count += 1
        except Exception as e:
            log.error(f"Failed to export task {task.id}: {e}", exc_info=True)

    return exported_count


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for the script."""
    parser = argparse.ArgumentParser(
        description="Export Todoist tasks to Obsidian-compatible markdown files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                    # Export all tasks
  %(prog)s --date 2024-01-15                 # Export tasks completed on Jan 15, 2024
        """,
    )

    parser.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        default=None,
        help="Export tasks completed on a specific date (YYYY-MM-DD format)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging (DEBUG level)",
    )

    return parser


def main() -> None:
    """Main entry point for the script."""
    parser = create_parser()
    args = parser.parse_args()

    # Set log level
    if args.verbose:
        structlog.configure(
            processors=[
                structlog.dev.ConsoleRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(10),  # DEBUG level
            logger_factory=structlog.PrintLoggerFactory(),
            cache_logger_on_first_use=True,
        )

    # Check environment variables
    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        log.error("Missing required environment variable: TODOIST_API_TOKEN")
        sys.exit(1)

    folder = os.getenv("TODOIST_NOTES_FOLDER")
    if not folder:
        log.error("Missing required environment variable: TODOIST_NOTES_FOLDER")
        sys.exit(1)

    # Parse date if provided
    target_date = None
    if args.date:
        try:
            target_date = parse_date_string(args.date)
        except ValueError as e:
            log.error(str(e), exc_info=True)
            sys.exit(1)

    try:
        # Create client and export config
        # Always include completed tasks
        client = TodoistClient(token)
        export_config = ExportConfig(
            Path(folder), include_completed=True, include_comments=True
        )

        # Export tasks
        exported_count = export_tasks_internal(
            client,
            export_config,
            target_date,
        )

        log.info(f"Successfully exported {exported_count} Todoist tasks.")
    except TodoistAPIError as e:
        log.error(f"Todoist API Error: {e}", exc_info=True)
        sys.exit(1)
    except Exception as e:
        log.error(
            f"An unexpected error occurred during Todoist export: {e}", exc_info=True
        )
        sys.exit(1)


def read_obsidian_file(file_path: Path) -> str | None:
    """Read Obsidian markdown file with error handling.

    Args:
        file_path: Path to the markdown file

    Returns:
        File content or None if reading fails
    """
    try:
        with open(file_path, encoding="utf-8") as file:
            return file.read()
    except Exception as e:
        structlog.get_logger().error(f"Failed to read file {file_path}: {e}")
        return None


def write_obsidian_file(file_path: Path, content: str) -> bool:
    """Write content to Obsidian markdown file with error handling.

    Args:
        file_path: Path to the markdown file
        content: Content to write

    Returns:
        True if write successful, False otherwise
    """
    logger = structlog.get_logger()
    existing_content = None
    if file_path.exists():
        existing_content = read_obsidian_file(file_path)

    if existing_content is not None and existing_content != content:
        diff = difflib.unified_diff(
            existing_content.splitlines(keepends=True),
            content.splitlines(keepends=True),
            fromfile=f"a/{file_path.name}",
            tofile=f"b/{file_path.name}",
            lineterm="",  # To avoid extra newlines if splitlines(keepends=True) is used
        )
        diff_str = "".join(diff)
        if diff_str:  # Only log if there's an actual diff
            logger.info(
                "Obsidian file content diff before writing", file_path=file_path
            )
            logger.info(diff_str)

    try:
        with open(file_path, "w", encoding="utf-8") as file:
            file.write(content)
        return True
    except Exception as e:
        logger.error(f"Failed to write to file {file_path}: {e}")
        return False


if __name__ == "__main__":
    main()
