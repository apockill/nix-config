import os
import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence
import re

# Pattern for directories to wholesale ignore
_DEFAULT_IGNORES = (
    "build|"
    "cmake-build-debug|"
    "cmake-build-release|"
    "_build|"
    "vendor|"
    "third_party|"
    "__pycache__|"
    ".git|"
    ".venv|"
    ".idea|"
    "llm_context.md|"
    ".*.lock"
)

_MAX_FILE_SIZE_BYTES = 1 * 1024 * 1024  # 1 MB


def parse_arguments() -> argparse.Namespace:
    """Parses command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Generates a markdown file with directory context for LLMs."
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=Path,
        default=Path("llm_context.md"),
        help="Specify the output markdown file.",
    )
    parser.add_argument(
        "-n",
        "--project-name",
        type=str,
        default="Yet To Be Named",
        help="Specify the project name used in the markdown header.",
    )
    parser.add_argument(
        "-i",
        "--start-dir",
        type=Path,
        default=Path("."),
        help="The root directory to analyze for the tree structure.",
    )
    parser.add_argument(
        "--ignore-pattern",
        type=str,
        default="",
        help="Pipe-separated pattern of directories/files to ignore in the tree view (passed to 'tree -I').",
    )
    return parser.parse_args()


def generate_tree_output(start_dir: Path, ignore_pattern: str) -> Optional[str]:
    """
    Generates the directory tree string using the external 'tree' command.

    Args:
        start_dir: The directory to run 'tree' in.
        ignore_pattern: The pattern string to pass to 'tree -I'.

    Returns:
        The output string from the 'tree' command, or None if 'tree' fails.
    """
    if not start_dir.is_dir():
        print(f"Error: Start directory not found: {start_dir}", file=sys.stderr)
        return None

    tree_command = ["tree", "-I", ignore_pattern, str(start_dir)]
    print(f"Running command: {' '.join(tree_command)}")

    result = subprocess.run(
        tree_command,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",  # Explicitly set encoding
    )
    return result.stdout


def write_markdown_file(
    output_file: Path, project_name: str, tree_structure: str, file_contents: str
) -> None:
    """Writes the initial markdown content to the output file."""
    print(f"Generating LLM context file: {output_file}")
    try:
        with output_file.open("w", encoding="utf-8") as f:
            # 1. Add Initial Header and Description
            f.write(f"# Context for {project_name} Project\n\n")
            f.write(
                f"This document provides context for the {project_name} project, intended for use by LLMs.\n"
            )
            f.write(
                "It includes the project's directory structure and will later include contents of key files.\n\n"
                "Before answering the users prompt, create a mental model of the project, it's state,\n"
                "the interactions between objects, and the unfinished edges that still need developing.\n"
                "Create a succinct summary index of the project, and _then_ answer the users first query. Keep in mind the\n"
                "conversation will continue past the query, so the summary you create should be a helpful\n"
                "reference for you to answer future queries as well, not just for this specific query.\n\n"
            )

            # 2. Add Project Structure Tree
            f.write("## Project Structure\n\n")
            f.write("```shell\n")
            # Write the starting directory name, as 'tree' output usually omits the absolute root '.'
            f.write(f"{output_file.resolve().parent.name}\n")  # Show relative root name
            f.write(f"{tree_structure}\n")
            f.write("```\n\n")

            f.write(file_contents)

        print(f"Successfully generated initial context file: {output_file}")

    except IOError as e:
        print(f"Error writing to output file {output_file}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"An unexpected error occurred during file writing: {e}", file=sys.stderr)


def extract_file_contexts(
    start_dir: Path,
    ignore_patterns: str,
) -> str:
    """
    Recursively finds files matching include_patterns, skipping ignore_patterns,
    and returns their content formatted in simple Markdown code blocks.

    Args:
        start_dir: The root directory to search within.
        ignore_patterns: A regex to match against files we want to ignore

    Returns:
        A single string containing the formatted Markdown for all found files,
        starting with "# File Contents\n\n". Returns an empty string if no
        files are found or if start_dir is invalid.
    """
    if not start_dir.is_dir():
        print(f"Warning: Start directory not found: {start_dir}", file=sys.stderr)
        return ""

    # Create the regex patterns
    ignore_regex = None
    # 1. Split the input string by '|'
    parts = ignore_patterns.split("|")
    # 2. Escape each part to treat characters like '.' literally, and filter empty parts
    escaped_parts = [part for part in parts if part]
    if escaped_parts:
        # 3. Join the escaped parts back with '|' to form the regex OR
        joined_pattern = "|".join(escaped_parts)
        # 4. Anchor the pattern to match the whole name
        final_regex_pattern = f"^(?:{joined_pattern})$"
        try:
            ignore_regex = re.compile(final_regex_pattern)
        except re.error as e:
            print(
                f"Warning: Invalid regex pattern derived from ignore string: {e}. Ignoring the pattern.",
                file=sys.stderr,
            )
            ignore_regex = None  # Reset on error
    else:
        print(
            f"Warning: Ignore pattern string '{ignore_patterns}' resulted in no valid patterns.",
            file=sys.stderr,
        )

    markdown_parts = ["# File Contents\n"]  # Start with the main section header
    start_dir = start_dir.resolve()  # Work with absolute paths internally

    for root, dirs, files in os.walk(start_dir, topdown=True):
        current_path = Path(root)

        # Pruning Ignored Directories
        dirs[:] = [d for d in dirs if not ignore_regex.match(d)]

        # Processing Files
        files.sort()
        for filename in files:
            # Check if filename itself matches an ignore pattern
            if ignore_regex.match(filename):
                continue

            # Include this file
            full_path = current_path / filename
            relative_path = full_path.relative_to(start_dir)
            file_block = create_file_block(full_path, relative_path)
            if file_block is not None:
                markdown_parts += file_block

    # Combine all parts, adding an extra newline between sections
    return "\n".join(markdown_parts)


def create_file_block(full_path: Path, relative_path: Path) -> list[str] | None:
    """Create a file block of format
    # `path/to/file.txt`
    ```
    {file contents}
    ```
    """
    markdown_parts = []

    # --- 1. Get File Size and Check Limit ---
    try:
        stats = full_path.stat()
        size_bytes = stats.st_size
    except FileNotFoundError:
        # Although os.walk should yield existing files, add check for robustness
        print(
            f"Warning: File not found during stat: {relative_path}. Skipping.",
            file=sys.stderr,
        )
        return None
    except OSError as stat_err:
        # Catch other stat errors like permission denied
        print(
            f"Warning: Could not get stats for file {relative_path}: {stat_err}. Skipping.",
            file=sys.stderr,
        )
        return None

    # Check if file exceeds the size limit
    if size_bytes > _MAX_FILE_SIZE_BYTES:
        print(f"Warning: Ignoring not-ignored file that was too large {relative_path}")
        return None

    # Calculate size in KB for display
    size_kb = size_bytes / 1024.0

    # --- 2. Read File Content (if size is okay) ---
    try:
        # Attempt to read as UTF-8
        content = full_path.read_text(encoding="utf-8")
    except Exception as read_err:
        print(
            f"Warning: Could not read file {relative_path}: {read_err}. Skipping.",
            file=sys.stderr,
        )
        return None

    # --- 3. Format the Markdown Section ---
    # Add the file size in KB to the header
    markdown_parts.append(f"## `{relative_path}`\n")
    markdown_parts.append(f"**File Size**: {size_kb:.1f} KB\n")
    markdown_parts.append("```\n")  # Simple code fence
    markdown_parts.append(f"{content.strip()}\n")  # Strip leading/trailing whitespace
    markdown_parts.append("```\n")
    return markdown_parts


def make_llm_context() -> None:
    """Main execution function."""
    args = parse_arguments()
    all_ignores = _DEFAULT_IGNORES + (
        "|" + args.ignore_pattern if args.ignore_pattern else ""
    )
    tree_output = generate_tree_output(
        args.start_dir.resolve(), all_ignores
    )  # Use resolved path

    file_context = extract_file_contexts(args.start_dir, all_ignores)

    if tree_output is not None:
        write_markdown_file(
            args.output_file, args.project_name, tree_output, file_context
        )
    else:
        print("Failed to generate tree structure. Aborting.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    make_llm_context()
