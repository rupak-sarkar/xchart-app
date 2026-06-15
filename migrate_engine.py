"""migrate_engine.py — Move engine files from xchart-app to xchart-engine"""

import os
import shutil
import subprocess

# Files and folders to move to private repo
MOVE_LIST = [
    "engine",
    "app.py",
    "data_fetcher.py",
    "requirements.txt",
]

# Workflows to COPY (not move — we'll create new ones in engine repo)
WORKFLOW_COPY = [
    ".github/workflows/run_engine.yml",
    ".github/workflows/update_tickers.yml",
    ".github/workflows/data_fetcher.yml",
]

GITHUB_USER = "rupak-sarkar"
ENGINE_REPO = "xchart-engine"
PUBLIC_REPO = "xchart-app"


def main():
    token = os.environ.get("ENGINE_TOKEN", "")
    if not token:
        print("ERROR: ENGINE_TOKEN not set!")
        return

    print("=" * 70)
    print("  ENGINE MIGRATION — xchart-app → xchart-engine")
    print("=" * 70)

    # ── Step 1: Clone engine repo ──
    print("\n[1/5] Cloning xchart-engine...")
    engine_dir = "/tmp/xchart-engine"
    if os.path.exists(engine_dir):
        shutil.rmtree(engine_dir)

    clone_url = f"https://x-access-token:{token}@github.com/{GITHUB_USER}/{ENGINE_REPO}.git"
    result = subprocess.run(
        ["git", "clone", clone_url, engine_dir],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("  ERROR cloning:", result.stderr)
        return
    print("  ✅ Cloned xchart-engine")

    # ── Step 2: Copy engine files ──
    print("\n[2/5] Copying engine files...")
    copied = 0
    for item in MOVE_LIST:
        if os.path.exists(item):
            dest = os.path.join(engine_dir, item)
            if os.path.isdir(item):
                if os.path.exists(dest):
                    shutil.rmtree(dest)
                shutil.copytree(item, dest)
                file_count = sum(len(files) for _, _, files in os.walk(item))
                print(f"  Copied dir: {item}/ ({file_count} files)")
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copy2(item, dest)
                print(f"  Copied file: {item}")
            copied += 1
        else:
            print(f"  SKIP (not found): {item}")

    # ── Step 3: Copy workflows ──
    print("\n[3/5] Copying workflows...")
    for wf in WORKFLOW_COPY:
        if os.path.exists(wf):
            dest = os.path.join(engine_dir, wf)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(wf, dest)
            print(f"  Copied: {wf}")
        else:
            print(f"  SKIP (not found): {wf}")

    # ── Step 4: Create cross-repo push workflow in engine ──
    print("\n[4/5] Creating cross-repo push workflow...")
    push_workflow = f"""name: Push Data to Public Repo
on:
  workflow_run:
    workflows: ["*"]
    types: [completed]
  workflow_dispatch:

jobs:
  push:
    runs-on: ubuntu-latest
    if: ${{{{ github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success' }}}}
    steps:
      - uses: actions/checkout@v4

      - name: Push output to public repo
        env:
          TOKEN: ${{{{ secrets.PUBLIC_REPO_TOKEN }}}}
        run: |
          cd /tmp
          git clone https://x-access-token:$TOKEN@github.com/{GITHUB_USER}/{PUBLIC_REPO}.git
          
          # Copy output data
          if [ -d "$GITHUB_WORKSPACE/output" ]; then
            cp -r $GITHUB_WORKSPACE/output/* {PUBLIC_REPO}/output/ 2>/dev/null || true
          fi
          if [ -d "$GITHUB_WORKSPACE/screener_data" ]; then
            cp -r $GITHUB_WORKSPACE/screener_data/* {PUBLIC_REPO}/screener_data/ 2>/dev/null || true
          fi
          if [ -d "$GITHUB_WORKSPACE/charts" ]; then
            cp -r $GITHUB_WORKSPACE/charts/* {PUBLIC_REPO}/charts/ 2>/dev/null || true
          fi
          
          cd {PUBLIC_REPO}
          git config user.name "Engine Bot"
          git config user.email "bot@xchart.in"
          git add -A
          git diff --staged --quiet || git commit -m "Data update $(date +%Y-%m-%d_%H:%M)"
          git push
"""
    push_wf_path = os.path.join(engine_dir, ".github/workflows/push_to_public.yml")
    os.makedirs(os.path.dirname(push_wf_path), exist_ok=True)
    with open(push_wf_path, "w") as f:
        f.write(push_workflow)
    print("  ✅ Created push_to_public.yml")

    # ── Step 5: Commit and push to engine repo ──
    print("\n[5/5] Pushing to xchart-engine...")
    os.chdir(engine_dir)
    subprocess.run(["git", "config", "user.name", "Migration Bot"], capture_output=True)
    subprocess.run(["git", "config", "user.email", "bot@xchart.in"], capture_output=True)
    subprocess.run(["git", "add", "-A"], capture_output=True)

    result = subprocess.run(
        ["git", "commit", "-m", "Migration: engine files from xchart-app"],
        capture_output=True, text=True
    )
    if "nothing to commit" in result.stdout:
        print("  No changes to commit")
    else:
        result = subprocess.run(["git", "push"], capture_output=True, text=True)
        if result.returncode == 0:
            print("  ✅ Pushed to xchart-engine")
        else:
            print("  ERROR pushing:", result.stderr)
            return

    # ── Step 6: Remove engine files from public repo ──
    os.chdir(os.environ.get("GITHUB_WORKSPACE", "/home/runner/work/xchart-app/xchart-app"))
    print("\n[6/6] Removing engine files from xchart-app...")
    removed = 0
    for item in MOVE_LIST:
        if os.path.exists(item):
            if os.path.isdir(item):
                shutil.rmtree(item)
                print(f"  Removed dir: {item}/")
            else:
                os.remove(item)
                print(f"  Removed file: {item}")
            removed += 1

    # Remove engine workflows from public repo
    for wf in WORKFLOW_COPY:
        if os.path.exists(wf):
            os.remove(wf)
            print(f"  Removed workflow: {wf}")

    subprocess.run(["git", "add", "-A"], capture_output=True)

    print("\n" + "=" * 70)
    print("  MIGRATION COMPLETE")
    print("=" * 70)
    print(f"""
  ✅ {copied} items copied to xchart-engine (PRIVATE)
  ✅ {removed} items removed from xchart-app (PUBLIC)
  ✅ Cross-repo push workflow created

  IMPORTANT — Do this after migration:
  
  1. Go to xchart-engine repo → Settings → Secrets → Actions
     Add secret: PUBLIC_REPO_TOKEN = (same PAT token)
     
  2. Go to xchart-engine repo → Settings → Secrets → Actions  
     Add secret: ENGINE_REPO_TOKEN = (same PAT token)
     
  3. Verify xchart-engine has these files:
     ├── engine/
     ├── app.py
     ├── data_fetcher.py
     ├── requirements.txt
     └── .github/workflows/

  4. Test: Trigger a workflow in xchart-engine
     → Should run engine + push data to xchart-app
""")


if __name__ == "__main__":
    main()
