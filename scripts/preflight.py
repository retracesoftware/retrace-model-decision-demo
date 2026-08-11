from scripts.run_demo import DemoPreflightError, verify_docker


if __name__ == "__main__":
    try:
        verify_docker()
    except DemoPreflightError as error:
        raise SystemExit(f"Demo preflight failed: {error}") from None
    print("Docker is ready.")
