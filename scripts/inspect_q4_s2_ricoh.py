"""Compatibility entry point using the validated production Ricoh adapter."""
import sys
from run_h3e0a_preflight import main


if __name__ == "__main__":
    sys.argv[1:] = ["ricoh"]
    main()
