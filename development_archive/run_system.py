import subprocess
import sys
import os
import time

def run_system():
    # Use the current python executable
    python_exe = sys.executable
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    print("="*50)
    print("Starting FORVIA SMART MONITOR SYSTEM")
    print("="*50)
    
    # 1. Start Vision Loop
    print(f"\n[1/2] Launching Vision Processing Loop...")
    vision_proc = subprocess.Popen(
        [python_exe, "vision_loop_video.py"],
        cwd=root_dir
    )
    
    # Give vision loop a moment to initialize (SQL/MQTT)
    time.sleep(2)
    
    # 2. Start Dashboard
    print(f"[2/2] Launching Dashboard Interface...")
    dashboard_proc = subprocess.Popen(
        [python_exe, "Dashboard/main.py"],
        cwd=root_dir
    )
    
    print("\n" + "="*50)
    print("System is running.")
    print("Press Ctrl+C in this terminal to stop both applications.")
    print("="*50)
    
    try:
        # Keep the launcher alive while processes are running
        while True:
            if vision_proc.poll() is not None:
                print("\n[!] Vision Processing Loop has stopped.")
                break
            if dashboard_proc.poll() is not None:
                print("\n[!] Dashboard has stopped.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[!] Stopping system...")
    finally:
        # Cleanup
        if vision_proc.poll() is None:
            vision_proc.terminate()
        if dashboard_proc.poll() is None:
            dashboard_proc.terminate()
        print("Done.")

if __name__ == "__main__":
    run_system()
