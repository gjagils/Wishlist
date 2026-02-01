#!/usr/bin/env python3
"""
Process manager voor Wishlist applicatie.
Start en monitort alle processen: web app, worker, en email monitor.
"""
import os
import sys
import subprocess
import time
import signal
from threading import Thread

processes = {}
shutdown_requested = False


def start_process(name: str, script: str):
    """Start een proces en monitor het."""
    global shutdown_requested

    while not shutdown_requested:
        print(f"▶️  Starting {name}...")

        try:
            proc = subprocess.Popen(
                [sys.executable, script],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            processes[name] = proc

            # Stream output
            for line in proc.stdout:
                if line.strip():
                    print(f"[{name}] {line.rstrip()}")

            # Process beëindigd
            proc.wait()

            if shutdown_requested:
                print(f"✓ {name} gestopt")
                break

            # Crash - restart na 5 seconden
            print(f"⚠️  {name} crashed (exit code: {proc.returncode}), restart over 5s...")
            time.sleep(5)

        except Exception as e:
            print(f"❌ Fout bij starten {name}: {e}")
            if not shutdown_requested:
                time.sleep(5)


def signal_handler(signum, frame):
    """Handle shutdown signals."""
    global shutdown_requested
    print("\n🛑 Shutdown signal ontvangen, stoppen processen...")
    shutdown_requested = True

    # Stop alle processen
    for name, proc in processes.items():
        try:
            print(f"   Stoppen {name}...")
            proc.terminate()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print(f"   Force kill {name}...")
            proc.kill()
        except Exception as e:
            print(f"   Fout bij stoppen {name}: {e}")

    sys.exit(0)


def main():
    """Main entry point."""
    print("=" * 60)
    print("📚 Wishlist Manager - Multi-Process Startup")
    print("=" * 60)

    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    # Check required environment variables
    required_vars = [
        'SPOTWEB_BASE_URL',
        'SPOTWEB_APIKEY',
        'SAB_BASE_URL',
        'SAB_APIKEY'
    ]

    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        print(f"❌ Missende environment variables: {', '.join(missing_vars)}")
        sys.exit(1)

    # Email monitoring is optioneel
    email_enabled = bool(os.environ.get('EMAIL_ADDRESS') and os.environ.get('EMAIL_PASSWORD'))

    print("\n✓ Configuratie geladen")
    print(f"   Spotweb: {os.environ['SPOTWEB_BASE_URL']}")
    print(f"   SABnzbd: {os.environ['SAB_BASE_URL']}")
    print(f"   Email monitoring: {'Enabled' if email_enabled else 'Disabled'}")
    print()

    # Start processen in threads
    threads = []

    # Web app
    t1 = Thread(target=start_process, args=("webapp", "app.py"), daemon=True)
    t1.start()
    threads.append(t1)
    time.sleep(2)  # Laat web app eerst starten

    # Worker
    t2 = Thread(target=start_process, args=("worker", "worker.py"), daemon=True)
    t2.start()
    threads.append(t2)

    # Email monitor (optioneel)
    if email_enabled:
        t3 = Thread(target=start_process, args=("email", "email_monitor.py"), daemon=True)
        t3.start()
        threads.append(t3)
    else:
        print("[INFO] Email monitoring uitgeschakeld (EMAIL_ADDRESS/EMAIL_PASSWORD niet ingesteld)")

    print("\n✓ Alle processen gestart")
    print("=" * 60)
    print()

    # Wacht tot shutdown
    try:
        while not shutdown_requested:
            time.sleep(1)
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)


if __name__ == "__main__":
    main()
