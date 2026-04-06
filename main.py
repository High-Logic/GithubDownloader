import os
import sys
import json
import requests
import argparse
import platform
import subprocess
from urllib.parse import urlparse, unquote
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import List, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.progress import (
    Progress,
    TextColumn,
    BarColumn,
    DownloadColumn,
    TransferSpeedColumn,
    TimeRemainingColumn,
    TaskID,
)
from rich.prompt import Prompt

# --- Configuration Management ---

CONFIG_FILE = "config.json"
console = Console()


@dataclass
class Config:
    token: str = ""

    @classmethod
    def load(cls) -> "Config":
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r") as f:
                    data = json.load(f)
                    return cls(token=data.get("token", ""))
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        with open(CONFIG_FILE, "w") as f:
            json.dump({"token": self.token}, f)


# --- Core Downloader Logic ---

@dataclass
class FileMetadata:
    download_url: str
    file_path: str
    size: int


class GithubDownloader:
    BASE_API_URL = "https://api.github.com/repos"

    def __init__(self, max_workers: int = 10, skip_existing: bool = True, token: str = ""):
        self.max_workers = max_workers
        self.skip_existing = skip_existing
        self.session = requests.Session()
        if token:
            self.set_token(token)

    def set_token(self, token: str) -> None:
        if token:
            self.session.headers.update({"Authorization": f"token {token}"})

    @staticmethod
    def parse_github_url(url: str) -> Tuple[str, str, str, str]:
        """Parses GitHub URL and returns (owner, repo, branch, path)"""
        try:
            parsed_url = urlparse(url)
            parts = unquote(parsed_url.path).strip('/').split('/')
            # Expected format: owner/repo/tree/branch/path
            if len(parts) < 4 or parts[2] != 'tree':
                raise ValueError("Invalid format. Use: https://github.com/user/repo/tree/branch/path")
            return parts[0], parts[1], parts[3], '/'.join(parts[4:])
        except Exception as e:
            raise ValueError(f"Error parsing URL: {e}")

    def get_api_url(self, url: str) -> str:
        if url.startswith(self.BASE_API_URL):
            return url
        owner, repo, branch, path = self.parse_github_url(url)
        return f"{self.BASE_API_URL}/{owner}/{repo}/contents/{path}?ref={branch}"

    def get_metadata(self, url: str) -> List[FileMetadata]:
        """Recursively fetch file metadata from GitHub API."""
        api_url = self.get_api_url(url)
        response = self.session.get(api_url)

        if response.status_code == 403:
            raise Exception("API rate limit exceeded or invalid token.")
        response.raise_for_status()

        files_metadata = []
        dirs_to_process = []

        items = response.json()
        if not isinstance(items, list):  # Single file case
            items = [items]

        for item in items:
            if item['type'] == 'file':
                files_metadata.append(FileMetadata(
                    download_url=item['download_url'],
                    file_path=item['path'],
                    size=item['size']
                ))
            elif item['type'] == 'dir':
                dirs_to_process.append(item['url'])

        if dirs_to_process:
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                results = executor.map(self.get_metadata, dirs_to_process)
                for subdir_metadata in results:
                    files_metadata.extend(subdir_metadata)

        return files_metadata

    def download_file(self, file_metadata: FileMetadata, output_dir: str, progress: Progress, task_id: TaskID) -> None:
        file_path = os.path.join(output_dir, file_metadata.file_path)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        if os.path.exists(file_path) and self.skip_existing:
            progress.update(task_id, advance=file_metadata.size)
            return

        response = self.session.get(file_metadata.download_url, stream=True)
        response.raise_for_status()

        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    progress.update(task_id, advance=len(chunk))


# --- UI & Interaction ---

def show_welcome():
    welcome_text = (
        "[bold cyan]GitHub Folder Downloader[/bold cyan]\n"
        "[dim]Download specific folders from GitHub without cloning the whole repo.[/dim]\n\n"
        "Usage:\n"
        "1. Paste a GitHub folder URL (e.g., .../tree/main/folder)\n"
        "2. Type [bold yellow]'token'[/bold yellow] to set/update your GitHub Personal Access Token\n"
        "3. Type [bold red]'exit'[/bold red] to quit"
    )
    console.print(Panel(welcome_text, border_style="blue", expand=False))


def run_download(url: str, output: str, token: str, workers: int):
    downloader = GithubDownloader(max_workers=workers, token=token)

    try:
        with console.status("[bold green]Scanning repository structure..."):
            files = downloader.get_metadata(url)

        if not files:
            console.print("[yellow]No files found in the specified path.[/yellow]")
            return

        total_size = sum(f.size for f in files)

        # Summary Table
        table = Table(title="Task Information", show_header=False, border_style="dim")
        table.add_row("Target URL", url)
        table.add_row("Output Dir", output)
        table.add_row("Total Files", str(len(files)))
        table.add_row("Total Size", f"{total_size / (1024 * 1024):.2f} MB")
        console.print(table)

        # Progress Setup
        progress = Progress(
            TextColumn("[bold blue]{task.description}"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.0f}%",
            DownloadColumn(),
            TransferSpeedColumn(),
            TimeRemainingColumn(),
        )

        with progress:
            main_task = progress.add_task("Downloading...", total=total_size)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(downloader.download_file, f, output, progress, main_task)
                    for f in files
                ]
                for future in futures:
                    future.result()  # Catch exceptions if any

        console.print("\n[bold green]✓ All files downloaded successfully![/bold green]\n")

        # --- 完成后打开文件夹逻辑 ---
        try:
            abs_path = os.path.abspath(output)
            if platform.system() == "Windows":
                os.startfile(abs_path)
            elif platform.system() == "Darwin":  # macOS
                subprocess.run(["open", abs_path])
            else:  # Linux
                subprocess.run(["xdg-open", abs_path])
        except Exception as e:
            console.print(f"[dim red]Note: Could not open folder automatically: {e}[/dim red]")

    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")


def main():
    parser = argparse.ArgumentParser(description="GitHub Folder Downloader CLI")
    parser.add_argument("url", nargs="?", help="GitHub folder URL")
    parser.add_argument("--output", "-o", default="./Downloads", help="Local output directory")
    parser.add_argument("--token", "-t", help="GitHub Personal Access Token")
    parser.add_argument("--workers", "-w", type=int, default=10, help="Number of parallel threads")
    args = parser.parse_args()

    config = Config.load()

    # Priority: CLI Argument > Config File
    current_token = args.token if args.token else config.token

    # CLI Mode
    if args.url:
        run_download(args.url, args.output, current_token, args.workers)
        return

    # Interactive Mode
    show_welcome()
    while True:
        user_input = Prompt.ask("\n[bold cyan]Input URL or Command[/bold cyan]").strip()

        if not user_input or user_input.lower() == "exit":
            break

        if user_input.lower() == "token":
            new_token = Prompt.ask("Enter your GitHub Token (will be saved)")
            config.token = new_token
            config.save()
            current_token = new_token
            console.print("[green]Token updated successfully![/green]")
            continue

        if "github.com" in user_input:
            # Check for token once if never set
            if not current_token:
                console.print("[yellow]Hint: Using a Token avoids GitHub API rate limits.[/yellow]")
                token_input = Prompt.ask("Enter GitHub Token (press Enter to skip)", default="")
                if token_input:
                    config.token = token_input
                    config.save()
                    current_token = token_input

            run_download(user_input, args.output, current_token, args.workers)
        else:
            console.print("[red]Invalid input. Please enter a valid GitHub URL or 'token'/'exit'.[/red]")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user. Exiting...[/yellow]")
        sys.exit(0)
