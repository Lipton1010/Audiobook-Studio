"""Explicit optional narrator selection. Opening this window never downloads models."""
import json
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk, filedialog

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from app.model_hardware import MODEL_CHOICES, inventory, describe


def download_details():
    drama=json.loads((REPO/'install/drama3-pack.json').read_text())
    checker=json.loads((REPO/'install/parakeet-pack.json').read_text())
    runtime=drama['runtime'];weights=drama['model']
    lines=['\nDownload sources and payload sizes (dependencies/cache are additional):',
           f"Drama native runtime: {runtime['archive']['bytes']:,} bytes; {runtime.get('download_url') or 'verified local ZIP required'}",
           f"Drama Q3 weights: {weights['bytes']:,} bytes; https://huggingface.co/{weights['repo']}/tree/{weights['revision']}",
           'Drama model terms: '+weights['license_url'],
           f"Parakeet checker: {sum(f['bytes'] for f in checker['files']):,} bytes; https://huggingface.co/{checker['repo']}/tree/{checker['revision']}",
           'Checker terms: '+checker['license_url']]
    summary=json.loads((REPO/'install/model-download-summary.json').read_text())
    for item in summary['vibevoice']:
        lines.append(f"{item['name']}: {item['bytes']:,} bytes; {item['source']} ; model-card license: {item['card_license']}")
    lines.append('Chatterbox: existing legacy jobs remain supported. Its historical ~3 GB download is not a frozen tested pack, so this new GUI does not offer a fresh download yet.')
    return '\n'.join(lines)


def main():
    root = tk.Tk()
    root.title("Storybird: optional narrator setup")
    root.geometry("900x760")
    root.minsize(720, 600)
    selected = tk.StringVar(value="none")
    accepted = tk.BooleanVar(value=False)
    state = {"running": False}
    ttk.Label(root, text="Check this machine, choose a narrator, then review its terms.",
              font=("Segoe UI", 12)).pack(anchor="w", padx=16, pady=12)
    panel = ttk.Frame(root)
    panel.pack(fill="both", expand=True, padx=16)
    details = tk.Text(panel, wrap="word", height=20)
    scrollbar = ttk.Scrollbar(panel, command=details.yview)
    details.configure(yscrollcommand=scrollbar.set)
    details.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def refresh():
        state["machine"] = inventory(REPO)
        details.configure(state="normal")
        details.delete("1.0", "end")
        details.insert("end", describe(state["machine"]) + "\n" + download_details())
        details.configure(state="disabled")
        accepted.set(False)

    controls = ttk.Frame(root)
    controls.pack(fill="x", padx=16, pady=8)
    for key, model in MODEL_CHOICES.items():
        ttk.Radiobutton(controls, text=model["name"], variable=selected, value=key,
                        command=lambda: accepted.set(False)).pack(anchor="w")
    ttk.Checkbutton(root, text="I reviewed this model's linked terms, hardware caveats and download requirements.",
                    variable=accepted).pack(anchor="w", padx=16, pady=8)
    status = tk.StringVar(value="No model selected for download. Existing jobs are unchanged.")
    ttk.Label(root, textvariable=status, wraplength=850).pack(anchor="w", padx=16, pady=8)
    buttons = ttk.Frame(root)
    buttons.pack(fill="x", padx=16, pady=12)

    def finish(code):
        state["running"] = False
        install.configure(state="normal")
        recheck.configure(state="normal")
        status.set(("Setup completed. Restart Storybird when no jobs are running to load the new runtime paths." if code == 0 else "Setup failed; inspect the log before retrying.") +
                   " Log: " + str(REPO / "model_setup.log"))

    def start():
        if state["running"]:
            return
        choice = selected.get()
        if choice == 'chatterbox':
            messagebox.showinfo('Existing Chatterbox runtimes', 'Existing jobs and configured Chatterbox runtimes remain available. A frozen tested fresh-download pack is not ready; no files or settings were changed.')
            return
        machine = inventory(REPO)
        if choice != "none" and (not accepted.get() or machine["selected_gpu"] is None):
            messagebox.showwarning("Review required", "Confirm the selected model terms and hardware caveats. NVIDIA device detection must succeed before narrator setup. Core-only setup remains available.")
            return
        if not messagebox.askyesno("Install selected components?", "Install " + MODEL_CHOICES[choice]["name"] +
                                  "? Setup may download dependencies and model weights. Clean-install RAM/disk minima are not certified; see the machine report. Existing book settings will not be migrated."):
            return
        if choice == "drama3":
            import json
            manifest=json.loads((REPO/'install/drama3-pack.json').read_text())
            if not messagebox.askyesno("Drama model and runtime terms", "Drama uses the Fish Audio Community License (conditional commercial use), NVIDIA Parakeet CC-BY-4.0 and separate CUDA/runtime terms. Only use voice references you have permission to use. This downloads about 23 GB of weights plus runtime dependencies; keep 50 GiB free. Existing jobs and narrator defaults stay unchanged. Continue?"):
                return
            command=[sys.executable,str(REPO/'install/provision_drama3.py'),'--accept-model-terms','--accept-runtime-terms']
            if not manifest['runtime'].get('download_url'):
                archive=filedialog.askopenfilename(title="Select the reviewed Drama runtime ZIP (prerelease hosting pending)",filetypes=[("Runtime archive","*.zip")])
                if not archive:return
                command+=['--runtime-archive',archive]
        else:
            command = [sys.executable, str(REPO / "setup.py"), "--yes", "--narrator", choice,
                       "--runtime-root", str(REPO / "runtime")]
            if choice != "none":command.append("--accept-model-terms")
            if choice == "chatterbox":command.append("--prefetch-weights")
        state["running"] = True
        install.configure(state="disabled")
        recheck.configure(state="disabled")
        status.set("Installing selected components. Keep this window open; details go to model_setup.log.")

        def worker():
            try:
                with (REPO / "model_setup.log").open("w", encoding="utf-8") as log:
                    code = subprocess.run(command, cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode
            except OSError:
                code = -1
            root.after(0, finish, code)
        threading.Thread(target=worker, daemon=True).start()

    recheck = ttk.Button(buttons, text="Recheck hardware", command=refresh)
    recheck.pack(side="left")
    install = ttk.Button(buttons, text="Install selected components", command=start)
    install.pack(side="right")
    def close():
        if state["running"]:
            messagebox.showinfo("Setup still running", "Wait for setup to finish. Closing this window does not safely cancel package installation.")
        else:
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    refresh()
    root.mainloop()


if __name__ == "__main__":
    main()
