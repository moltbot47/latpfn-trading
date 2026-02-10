#!/usr/bin/env python3
"""
Download pretrained LaT-PFN model weights from Google Drive.

The checkpoint is stored at:
  https://drive.google.com/drive/folders/11dC1tbj0Vafr1Iqnk-IMBOpkI3-imYwL

Usage:
    python scripts/download_model.py
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def main():
    output_dir = Path("./models")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "lat_pfn_checkpoint.ckpt"

    if output_path.exists():
        print(f"Checkpoint already exists at {output_path}")
        print("Delete it first if you want to re-download.")
        return

    try:
        import gdown
    except ImportError:
        print("Installing gdown...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "gdown"])
        import gdown

    # Google Drive folder containing the checkpoint
    folder_url = "https://drive.google.com/drive/folders/11dC1tbj0Vafr1Iqnk-IMBOpkI3-imYwL"

    print(f"Downloading LaT-PFN checkpoint to {output_dir}/")
    print(f"Source: {folder_url}")
    print()

    # Download all files from the folder
    gdown.download_folder(folder_url, output=str(output_dir), quiet=False)

    # Find the downloaded .ckpt file and rename if needed
    ckpt_files = list(output_dir.glob("**/*.ckpt"))
    if ckpt_files:
        # Move/rename the first found checkpoint
        src = ckpt_files[0]
        if src != output_path:
            src.rename(output_path)
        print(f"\nCheckpoint saved to {output_path}")
        print(f"File size: {output_path.stat().st_size / 1e6:.1f} MB")
    else:
        print("\nWARNING: No .ckpt file found in the downloaded folder.")
        print("You may need to manually download from:")
        print(f"  {folder_url}")
        print(f"And place the checkpoint at: {output_path}")

    # Verify it loads
    try:
        import torch
        state = torch.load(output_path, map_location="cpu", weights_only=False)  # checkpoint has non-tensor data
        n_params = sum(v.numel() for v in state["state_dict"].values())
        print(f"Verified: {n_params:,} parameters loaded successfully")
    except Exception as e:
        print(f"Warning: Could not verify checkpoint: {e}")


if __name__ == "__main__":
    main()
