"""
Entry point for the GPU SLURM job.
Called by run_gpu.sh as: python3 hpg/run_pipeline.py
Using a real file (not python3 -c / heredoc) is required for
multiprocessing spawn mode — spawn re-imports __main__ by file path.
"""
import os
import sys
import pathlib

# Add project root to sys.path — running from hpg/ subdir would miss it
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

if __name__ == "__main__":
    rec_ids = [
        l.strip()
        for l in pathlib.Path("dataserver/rec_ids.txt").read_text().splitlines()
        if l.strip()
    ]

    from video.experiments import run_many

    run_many(
        rec_ids=rec_ids,
        combinations=os.environ.get("COMBINATION", "stable_match_farneback").split(","),
        run_id=os.environ.get("RUN_ID", "full_dataset_v1"),
        only_missing=True,
        save_videos=True,
        save_stage_grid=True,
        save_step_videos=False,
        workers=int(os.environ.get("WORKERS", os.environ.get("SLURM_CPUS_PER_TASK", "16"))),
    )
