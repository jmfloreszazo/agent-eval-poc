"""Simple calculator with basic operations and a command-line interface."""

import sys


def add(a: float, b: float) -> float:
    """Return the sum of a and b."""
    return a + b


def subtract(a: float, b: float) -> float:
    """Return a minus b."""
    return a - b


def multiply(a: float, b: float) -> float:
    """Return the product of a and b."""
    return a * b


def divide(a: float, b: float) -> float:
    """Return a divided by b.

    Raises ValueError if b is zero.
    """
    if b == 0:
        raise ValueError("Cannot divide by zero.")
    return a / b


OPERATIONS = {
    "add": add,
    "subtract": subtract,
    "multiply": multiply,
    "divide": divide,
}


def main(argv: list[str]) -> int:
    """CLI entry point: <operation> <a> <b>."""
    if len(argv) != 3 or argv[0] not in OPERATIONS:
        operations = ", ".join(OPERATIONS)
        print(f"Usage: python calculator.py <{operations}> <a> <b>")
        return 1

    operation = argv[0]
    try:
        a = float(argv[1])
        b = float(argv[2])
    except ValueError:
        print("Operands must be numbers.")
        return 1

    try:
        result = OPERATIONS[operation](a, b)
    except ValueError as error:
        print(error)
        return 1

    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

# note: see README for the agent workflow
