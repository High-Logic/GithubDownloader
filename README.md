# GitHub Folder Downloader

A high-performance CLI tool to download specific folders from GitHub repositories recursively without cloning the entire
repository.

![Terminal Screenshot](./Assets/screenshot.png)

## 🚀 Download

[**Get the Latest Release**](https://github.com/High-Logic/GithubDownloader/releases/download/V0.1/GithubDownloader.zip)

## 🛠️ How to Use

### Basic (Interactive Mode)

Simply run the program and follow the prompts:

- **Windows:** `GithubDownloader.exe`
- **Python:** `python main.py`

### Advanced (CLI Mode)

You can also run it via **PowerShell** or **CMD** for automation:

```powershell
# Basic usage
.\GithubDownloader.exe "https://github.com/user/repo/tree/main/folder"

# Specify output directory and thread count
.\GithubDownloader.exe "URL" --output "./MyFolder" --workers 15

# Use a Personal Access Token to avoid API limits
.\GithubDownloader.exe "URL" --token "your_github_token"