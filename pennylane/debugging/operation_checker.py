# Copyright 2018-2022 Xanadu Quantum Technologies Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
r"""
This file contains the OperationChecker debugging and developing tool.
"""
from collections.abc import Sequence
import inspect

import scipy.linalg as la

import pennylane as qml
from pennylane import numpy as np
from pennylane.operation import (
    MatrixUndefinedError,
    SparseMatrixUndefinedError,
    GeneratorUndefinedError,
    DiagGatesUndefinedError,
    EigvalsUndefinedError,
    TermsUndefinedError,
    DecompositionUndefinedError,
    AnyWires,
)

_colors = {
    "error": "91",  # red
    "hint": "93",  # yellow
    "comment": 94,  # blue
    "pass": "92",  # green
}

verbosity_levels = {"error": 0, "hint": 1, "comment": 2, "pass": 3}
levels_verbosity = {val: key for key, val in verbosity_levels.items()}

_default_methods_to_check = [
    ("compute_eigvals", EigvalsUndefinedError, False),
    ("compute_matrix", MatrixUndefinedError, False),
    ("compute_sparse_matrix", SparseMatrixUndefinedError, False),
    ("compute_terms", TermsUndefinedError, False),
    ("compute_decomposition", DecompositionUndefinedError, True),
    ("compute_diagonalizing_gates", DiagGatesUndefinedError, True),
]


def equal_up_to_phase(mat1, mat2, atol=1e-10):
    r"""Check whether two matrices are equal up to a scalar
    prefactor of the form :math:`\exp(i\phi)`.

    Args:
        mat1 (array_like): First matrix to check for equality
        mat2 (array_like): Second matrix to check for equality
        atol (float): Absolute tolerance for the check for equality

    Return:
        bool: Whether the two input matrices are equal up to a scalar
        phase prefactor.
    """
    # Check whether the matrices are equal
    if np.allclose(mat1, mat2, atol=atol, rtol=0.0):
        return True

    # Compute the potential scalar prefactor from the first nonzero entry of mat2
    ids = np.where(np.round(mat2, 10))
    idx = (ids[0][0], ids[1][0])
    phase = mat1[idx] / mat2[idx]

    # Return whether the matrices are equal, accounting for the potential scalar prefactor
    return np.allclose(mat1, mat2 * phase, atol=atol, rtol=0.0)


def is_diagonal(matrix):
    r"""Check whether a matrix is a diagonal matrix

    Args:
        matrix (array_like): Matrix to check

    Returns:
        bool: Whether the input matrix is a diagonal matrix
    """
    # Extract the diagonal, subtract it from the input, and check whether the result is 0.
    off_diagonal = matrix - np.diag(np.diag(matrix))
    return np.allclose(off_diagonal, np.zeros_like(matrix))


def wrap_op_method(op, method, expected_exc):
    r"""Wrap a method of an operation with a try-except clause, allowing for an expected
    exception and catching (and returning) other exceptions.

    Args:
        op (type or .operation.Operation): Operation that has the method to be wrapped
        method (str): Name of the method to be wrapped
        expected_exc (type): Exception type to ignore

    Returns:
        callable: The wrapped method of the operation.

    The object returned by the returned callable differs, depending on the scenario:

      - If the method succeeds, the return value of the method is returned,
      - If the ``expected_exc`` is raised, ``None`` is returned,
      - If another exception is raised, it is returned (but not raised).
    """
    _method = getattr(op, method)

    def wrapped_method(*args, **kwargs):
        r"""Wrapped operation method that tolerates an expected exception
        and catches (and returns) all other exceptions."""
        try:
            return _method(*args, **kwargs)
        except expected_exc:
            return None
        except Exception as e:
            return e

    return wrapped_method


def matrix_from_matrix(op, par, wires):
    r"""Get the matrix of an operation, using ``get_matrix``.

    Args:
        op (type): Operation type to obtain the matrix for
        par (array_like): Parameters of the operation
        wires (.wires.Wires): Wires of the operation

    Returns:
        object: Matrix of the operation if it is defined and no problem occured
        with ``get_matrix``. ``None`` if no matrix is defined via ``get_matrix``
        or ``Exception`` if an error occured.
    """
    instance = op(*par, wires=wires)
    return wrap_op_method(instance, "get_matrix", MatrixUndefinedError)()


def matrix_from_sparse_matrix(op, par, wires):
    r"""Get the matrix of an operation, using ``sparse_matrix``.

    Args:
        op (type): Operation type to obtain the matrix for
        par (array_like): Parameters of the operation
        wires (.wires.Wires): Wires of the operation

    Returns:
        object: Matrix of the operation if it is defined and no problem occured
        with ``sparse_matrix``. ``None`` if no matrix is defined via ``sparse_matrix``
        or ``Exception`` if an error occured.
    """
    instance = op(*par, wires=wires)
    smat = wrap_op_method(instance, "sparse_matrix", SparseMatrixUndefinedError)()
    if smat is None or isinstance(smat, Exception):
        return smat
    return qml.matrix(smat)


def matrix_from_terms(op, par, wires):
    r"""Get the matrix of an operation, using its ``terms``.

    Args:
        op (type): Operation type to obtain the matrix for
        par (array_like): Parameters of the operation
        wires (.wires.Wires): Wires of the operation

    Returns:
        object: Matrix of the operation if it is defined and no problem occured
        with ``terms``. ``None`` if no terms are defined via ``terms``
        or ``Exception`` if an error occured.
    """
    instance = op(*par, wires=wires)
    terms = wrap_op_method(instance, "terms", TermsUndefinedError)()
    if terms is None or isinstance(terms, Exception):
        return terms

    return np.sum([c * qml.matrix(op) for c, op in zip(*terms)], axis=0)


def matrix_from_decomposition(op, par, wires):
    r"""Get the matrix of an operation, using its ``decomposition``.

    Args:
        op (type): Operation type to obtain the matrix for
        par (array_like): Parameters of the operation
        wires (.wires.Wires): Wires of the operation

    Returns:
        object: Matrix of the operation if it is defined and no problem occured
        with ``expand``. ``None`` if no decomposition is defined via ``expand``
        or ``Exception`` if an error occured.
    """
    instance = op(*par, wires=wires)
    tape = wrap_op_method(instance, "expand", DecompositionUndefinedError)()
    return qml.matrix(tape, wire_order=wires) if isinstance(tape, qml.tape.QuantumTape) else tape


def matrix_from_single_qubit_rot_angles(op, par, wires):
    r"""Get the matrix of an operation, using its ``single_qubit_rot_angles``.

    Args:
        op (type): Operation type to obtain the matrix for
        par (array_like): Parameters of the operation
        wires (.wires.Wires): Wires of the operation

    Returns:
        object: Matrix of the operation if it is defined and no problem occured
        with ``single_qubit_rot_angles``. ``None`` if no rotation angles are
        defined via ``single_qubit_rot_angles`` or ``Exception`` if an error occured.
    """
    instance = op(*par, wires=wires)
    try:
        angles = instance.single_qubit_rot_angles()
    except (AttributeError, NotImplementedError):
        return None
    with qml.tape.QuantumTape() as tape:
        qml.RZ(angles[0], wires=wires)
        qml.RY(angles[1], wires=wires)
        qml.RZ(angles[2], wires=wires)
    return qml.matrix(tape)


def matrix_from_generator(op, par, wires):
    r"""Get the matrix of an operation, using its ``generator``.

    Args:
        op (type): Operation type to obtain the matrix for
        par (array_like): Parameters of the operation
        wires (.wires.Wires): Wires of the operation

    Returns:
        object: Matrix of the operation if it is defined and no problem occured
        with ``generator``. ``None`` if no generator is defined via ``generator``
        or ``Exception`` if an error occured.
    """
    instance = op(*par, wires=wires)
    gen = wrap_op_method(instance, "generator", GeneratorUndefinedError)()
    if gen is None or isinstance(gen, Exception):
        return None
    mat = qml.matrix(gen)
    return la.expm(1j * par[0] * mat)


decomposition_methods = [
    matrix_from_single_qubit_rot_angles,
    matrix_from_matrix,
    matrix_from_sparse_matrix,
    matrix_from_terms,
    matrix_from_decomposition,
    matrix_from_generator,
]


class CheckerError(Exception):
    """An internal error raised in OperationChecker used to mark specific exceptions."""


class OperationChecker:
    r"""Check one or multiple operation subclasses to define all required properties,
    be well-defined, and have consistent properties.

    Args:
        verbosity (str): How much output to print during execution (also see below):

            - ``"pass"``: Print all errors, hints, comments and status reports;

            - ``"comment"``: Like ``"pass"`` but without status reports;

            - ``"hint"``: Only print errors and hints;

            - ``"error"``: Only print errors.

        max_num_params (int): Largest number of parameters to check for operations
            that do not provide a fixed number of parameters via ``num_params`` themselves.
        print_color (bool): Whether or not to use colors in the terminal and returned outputs.
        tol (float): Numeric (absolute) tolerance for comparing matrices.

    The categorization of test results and of the associated messages is as follows:

    - ``"pass"``: Status reports e.g. after a successfully completed run.

    - ``"comment"``: Comments regarding certain properties of the tested operation(s).
      These does not require any action to change the operation but is used to raise awareness
      for behaviour that might be unexpected or differing from common operations.

    - ``"hint"``: Remarks similar to warnings that indicate concrete hints to change the checked
      operation(s). The recommended changes are expected to improve the code quality, performance
      or consistency with other operations.

    - ``"error"``: Problems with the checked operation(s) that require changes. These problems
      might be in the core of the ``Operation``, preventing instantiation, or in a specific
      method or property that is rendered unusable or inconsistent by the problem.
    """

    def __init__(self, verbosity="pass", max_num_params=10, print_color=True, tol=1e-5):
        # pylint: disable=too-many-instance-attributes
        self._verbosity = {
            key for key, val in verbosity_levels.items() if val <= verbosity_levels[verbosity]
        }
        self.max_num_params = max_num_params
        self.print_color = print_color
        self.tol = tol
        self.results = self.output = self.tmp = self.seed = None

    def __call__(self, op, parameters=None, wires=None, seed=None):
        r"""Call the OperationChecker on one or multiple operations.

        Args:
            op (type or .operation.Operation): Operation(s) to check. Allowed to be a ``Sequence``
                of types or instances instead, in which case the function iterates over all objects.
            parameters (Sequence[int or float]): Parameters with which the operation(s) is/are expected
                to work. If ``op`` contains multiple types and ``parameters`` only contains one
                set of parameters, they are broadcast to all operations.
                Ignored for those objects in ``op`` that are not types but a class instance.
            wires (.wires.Wires): Wires with which the operation(s) is/are expected to work.
                If ``op`` contains multiple types and ``wires`` only contains one wires object,
                it is broadcast to all operations.
                Ignored for those objects in ``op`` that are not types but a class instance.
            seed (int): Seed for random generation of parameters.

        Returns:
            dict: The result status for each checked operation, corresponding to the four levels
            ``"error"``, ``"hint"``, ``"comment"`` and ``"pass"``.
            dict: The text printed to the terminal for each checked operation.
        """
        if isinstance(op, Sequence):
            # A Sequence of operations was passed, make sure the parameters
            # and wires are also a Sequence of the same length
            if parameters is None or not isinstance(parameters[0], Sequence):
                # Broadcast the parameters
                parameters = [parameters] * len(op)
            else:
                # Check number of sets of parameters to match the number of operations
                assert len(parameters) == len(op)
            if wires is None or isinstance(wires, qml.wires.Wires):
                # Broadcast the wires
                wires = [wires] * len(op)
            else:
                # Check number of sets of wires to match the number of operations
                assert len(wires) == len(op)

        else:
            op = [op]
            parameters = [parameters]
            wires = [wires]

        self.seed = seed
        # Initialize result status for all operations
        self.results = {op_: "pass" for op_ in op}
        self.output = {}
        for op_, parameters_, wires_ in zip(op, parameters, wires):
            # Temporary storage per operation
            self.tmp = {
                "printed_header": False,  # Header for this op has not been printed yet
                "op": op_,  # Currently investigated operation
                "res": max(verbosity_levels.values()),  # Current result status
                "name": op_.name if isinstance(op_, qml.operation.Operation) else op_.__name__,
            }
            self.output[op_] = ""

            self.check_single_operation(op_, parameters_, wires_)

            # Store the result for this operation outside of tmp and print summary per op
            self.results[op_] = levels_verbosity[self.tmp["res"]]
            if self.results[op_] == "pass":
                self.print_(f"No problems have been found with the operation {op_}.\n", "pass")

        return self.results, self.output

    def print_(self, string, level=None):
        """Print a string if the verbosity level allows it, color it if applicable,
        and increment the result status for the currently checked operation if necessary.

        Args:
            string (str): String to be printed
            level (str): One of the verbosity levels (see class documentation)
                If the level is in the levels that are printed, print the string to console
                and store it in ``self.output``.

        Returns:

        A header is printed whenever a ``print_`` statement is executed first for
        a given operation (and the verbosity levels actually allow for an output).
        """

        self.tmp["res"] = min(self.tmp["res"], verbosity_levels[level])

        # Colorize the string
        if self.print_color and level is not None:
            string = f"\033[{_colors[level]}m{string}\033[0m"

        # Errors are always printed
        if level == "error" or level in self._verbosity:
            if not self.tmp["printed_header"]:
                header = f"Checking operation {self.tmp['op']} for consistency.\n" + "= " * 40
                print(header)
                self.output[self.tmp["op"]] += header
                self.tmp["printed_header"] = True
            print(string)
            self.output[self.tmp["op"]] += "\n" + string

    def check_single_operation(self, op, parameters, wires):
        """Check one operation subclass to define all required properties,
        be well-defined, and have consistent properties.

        Args:
            op (type): Operation to check.
            parameters (Sequence[int or float]): Parameters with which the operation(s)
                is/are expected to work.
            wires (.wires.Wires): Wires with which the operation(s) is/are expected to work.
        """
        if self.seed is not None:
            np.random.seed(self.seed)
        # Retrieve parameters and wires if op is operation instance instead of class
        if not inspect.isclass(op):
            parameters = op.parameters
            wires = op.wires
            op = type(op)

        wires = self._check_wires(op, wires)
        parameters = self._check_parameters(op, parameters)

        # Check class instantiation
        self._check_instantiation(op, parameters, wires)

        # Check methods to work with the same number of parameters as instantiation
        for method_tuple in _default_methods_to_check:
            self._check_single_method(op, method_tuple, parameters, wires)

        self._check_decompositions(op, parameters, wires)
        self._check_properties(op, parameters, wires)
        # self._check_differentiability(op, parameters, wires)

    def _check_wires(self, op, wires):
        """Check that ``num_wires`` is defined, that provided wires match that number
        and otherwise create correct number of wires.
        TODO: Check whether the following is reasonable:
        If ``num_wires`` is ``AnyWires``, its size is undetermined and we default to 2
        wires.
        """
        if type(op.num_wires) == property:
            self.print_(
                f"The operation {op} does not define the number of wires it acts on.", "error"
            )
            raise CheckerError("Fatal error: Subsequent checks will not be possible.")

        if wires is None:
            if op.num_wires != AnyWires:
                wires = qml.wires.Wires(range(op.num_wires))
            else:
                # Use a dummy case of 2 wires for operations with flexible number of wires
                wires = qml.wires.Wires([0, 1])
        else:
            if op.num_wires != AnyWires and len(wires) == op.num_wires:
                self.print_(
                    f"The number of provided wires ({len(wires)}) does not match the expected "
                    f"number ({op.num_wires}) for operation {op}",
                    "error",
                )
                raise CheckerError("Fatal error: Subsequent checks will not be possible.")

        return wires

    def _check_parameters(self, op, parameters):
        """Check whether ``num_params`` is defined, that provided parameters
        match that number if it is defined, and otherwise create parameter
        sets of length ``0`` to ``self.max_num_params``.
        """
        num_params_known = isinstance(op.num_params, int)
        self.tmp["num_params_known"] = num_params_known
        if parameters is None:
            if num_params_known:
                parameters = np.random.random(op.num_params)
            else:
                parameters = [np.random.random(num) for num in range(self.max_num_params)]
        elif num_params_known and len(parameters) != op.num_params:
            self.print_(
                f"The number of provided parameters ({len(parameters)}) does not match "
                f"the expected number ({op.num_params}) for operation {op}",
                "error",
            )
            raise CheckerError("Fatal error: Subsequent checks will not be possible.")

        return parameters

    def _check_instantiation(self, op, parameters, wires):
        """Check whether instantiation of an operation works, either
        with provided parameters and wires, or with a series of numbers
        of parameters. The number(s) of parameters with which instantiation
        works is stored in ``self.tmp["possible_num_params"]``."""
        if self.tmp["num_params_known"]:
            op(*parameters, wires=wires)
            return [op.num_params]

        possible_num_params = []
        for par in parameters:
            try:
                op(*par, wires=wires)
                possible_num_params.append(len(par))
            except:
                pass

        if len(possible_num_params) == 1:
            self.print_(
                f"Instantiating {op} only succeeded when using {possible_num_params[0]} "
                "parameter(s).\n"
                "Consider specifying the number of parameters by setting op.num_params.",
                "hint",
            )
        elif not possible_num_params:
            par_lens = [len(par) for par in parameters]
            err_str = f"Instantiating {op} did not succeed with any of\n" f"{par_lens} parameters."
            if len(parameters) == 1:
                err_str += (
                    "\nIt seems that you provided parameters of the wrong length "
                    "for this operation,\ncheck the input to check_operation."
                )
            self.print_(err_str, "error")

        self.tmp["possible_num_params"] = possible_num_params

    def _check_single_method(self, op, method_tuple, parameters, wires):
        """Check whether a specific method of an operation works with
        provided parameters and wires, or with the same number of
        parameters as the instantiation allowed."""

        method, expected_exc, use_wires = method_tuple
        wrapped_method = wrap_op_method(op, method, expected_exc)
        kwargs = {"wires": wires} if use_wires else {}
        if self.tmp["num_params_known"]:
            exc = wrapped_method(*parameters, **kwargs)
            if not isinstance(exc, Exception):
                # If no or the expected exception occured, return
                return

            # It might be that the "compute_..." method requires
            # different args than __init__ but that this is accomodated
            # for in the hyperparameters of the operation.
            try:
                instance = op(*parameters, wires=wires)
                getattr(instance, method.replace("compute", "get"))()
                self.print_(exc, "comment")
                self.print_(
                    f"Operation method {op}.{method} does not work\n"
                    f"with num_params ({op.num_params}) parameters (see above) but is "
                    "using additional (hyper)parameters.",
                    "comment",
                )
                # If the above indeed is the case, return
                return
            except Exception as f:
                self.print_(exc, "error")
                self.print_(f, "error")

            self.print_(
                f"Operation method {op}.{method} does not work\n"
                f"with num_params ({op.num_params}) parameters.",
                "error",
            )
            return

        failing_methods = []
        succeeding_methods = []
        for par in parameters:
            exc = wrapped_method(*par, **kwargs)
            num = len(par)
            if exc is None and num not in self.tmp["possible_num_params"]:
                succeeding_methods.append(num)
            elif isinstance(exc, Exception) and num in self.tmp["possible_num_params"]:
                failing_methods.append(num)

        if failing_methods:
            self.print_(
                f"Operation method {op}.{method} does not work\n"
                f"with number(s) of parameters {failing_methods}\n"
                "but instantiation works with this/these number(s) of parameters.",
                "error",
            )

        if succeeding_methods:
            self.print_(
                f"Operation method {op}.{method} works\n"
                f"with number(s) of parameters {succeeding_methods}\n"
                "but instantiation does not work with this/these number(s) of parameters.",
                "comment",
            )

    def _check_decompositions(self, op, parameters, wires):
        """Check that all defined decompositions work and yield the same matrix."""
        if self.tmp["num_params_known"]:
            parameters = [parameters]

        for par in parameters:
            matrices = [meth(op, par, wires) for meth in decomposition_methods]
            matrices = [mat for mat in matrices if mat is not None]
            for mat in matrices[1:]:
                if not equal_up_to_phase(matrices[0], mat, atol=self.tol):
                    self.print_(
                        f"Matrices do not coincide for {op}."
                        # f"\n{np.round(matrices[0], 5)}\n{np.round(mat, 5)}",
                        "error",
                    )

    def _check_properties(self, op, parameters, wires):
        """Check basic properties that need to be satisfied as well as the correctness
        of additional properties that are given by attributes of the operation."""
        if self.tmp["num_params_known"]:
            parameters = [parameters]

        for par in parameters:
            instance = op(*par, wires=wires)
            # Check that the matrix is square and has the correct size for op.num_wires
            mat = wrap_op_method(instance, "get_matrix", MatrixUndefinedError)()
            self._check_matrix_shape(mat, op)
            # Check that the eigenvalues are produced correctly
            eigvals = wrap_op_method(instance, "get_eigvals", EigvalsUndefinedError)()
            self._check_eigvals(eigvals, mat, op)
            # Check that the diagonalizing gates diagonalize the operation matrix
            diag_gates = wrap_op_method(instance, "diagonalizing_gates", DiagGatesUndefinedError)()
            self._check_diag_gates(diag_gates, mat, eigvals, op)
            # Check that the basis is given correctly
            self._check_basis(mat, instance)

    def _check_matrix_shape(self, matrix, op):
        """Check that a matrix attributed to an operation has the correct shape."""
        if matrix is None:
            return
        if not matrix.shape[0] == matrix.shape[1]:
            self.print_(f"The operation {op} defines a non-square matrix.", "error")
        mat_num_wires = int(np.log2(matrix.shape[0]))
        if not mat_num_wires == op.num_wires and op.num_wires != AnyWires:
            self.print_(
                f"The operation {op} defines a matrix for {mat_num_wires} wires but "
                f"is defined to have {op.num_wires} wires.",
                "error",
            )
        return

    def _check_eigvals(self, eigvals, matrix, op):
        """Check that produced eigvals for an operation coincide with the
        eigvals of a matrix representation of the same operation."""
        if matrix is None or eigvals is None:
            return
        mat_eigvals = np.linalg.eigvals(matrix)
        if not np.allclose(mat_eigvals, eigvals):
            self.print_(
                f"The eigenvalues of the matrix and the stored eigvals for {op} do not match.",
                "error",
            )
        return

    def _check_diag_gates(self, diag_gates, matrix, eigvals, op):
        """Check that the diagonalizing gates attributed to an operation
        produce a diagonal matrix, and that it has the correct eigenvalues."""
        if diag_gates is None or matrix is None:
            return
        if diag_gates == []:
            diag_mat = np.eye(matrix.shape[0])
        else:
            with qml.tape.QuantumTape() as tape:
                [op.queue() for op in diag_gates]
            diag_mat = qml.matrix(tape)

        diagonalized = diag_mat @ matrix @ diag_mat.conj().T
        if not is_diagonal(diagonalized):
            self.print_(
                f"The diagonalizing gates do not diagonalize the matrix for {op}.",
                "error",
            )
            return
        if eigvals is not None and not np.allclose(
            np.sort(eigvals), np.sort(np.diag(diagonalized))
        ):
            self.print_(
                "The diagonalizing gates diagonalize the matrix but produce wrong "
                f"eigenvalues for {op}.",
                "error",
            )
        return

    def _check_basis(self, matrix, instance):
        """Check that a matrix attributed to an operation is diagonal in the basis
        indicated by that operation's ``basis`` property."""
        try:
            basis = instance.basis
        except AttributeError:
            basis = None

        if basis is None or matrix is None:
            return

        if basis == "X":
            diag_gates = [qml.Hadamard]
        elif basis == "Y":
            diag_gates = [qml.PauliZ, qml.S, qml.Hadamard]
        elif basis == "Z":
            diag_gates = [qml.Identity]

        target_wires = qml.wires.Wires.unique_wires([instance.wires, instance.control_wires])
        with qml.tape.QuantumTape() as tape:
            for w in target_wires:
                [diag_gate(wires=w) for diag_gate in diag_gates]

        diag_mat = qml.operation.expand_matrix(qml.matrix(tape), target_wires, instance.wires)
        if not is_diagonal(diag_mat @ matrix @ diag_mat.conj().T):
            self.print_(
                f"The operation {instance.__class__} is not diagonal in the provided basis",
                "error",
            )
