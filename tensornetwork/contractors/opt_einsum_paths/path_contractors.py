# pylint: disable=cyclic-import
# Copyright 2019 The TensorNetwork Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Contractors based on `opt_einsum`'s path algorithms."""

import functools
import opt_einsum
# pylint: disable=line-too-long
from tensornetwork.network_operations import check_connected, get_all_edges, get_subgraph_dangling
# pylint: disable=line-too-long
from tensornetwork.network_components import get_all_nondangling, contract_parallel, contract_between
from tensornetwork.network_components import Edge, BaseNode
from tensornetwork.contractors.opt_einsum_paths import utils
from typing import Any, Optional, Sequence, Iterable

#TODO (martin): add return types of functions back once TensorNetwork is gone
#               remove _base_network
#               _base_nodes -> base


def base(nodes: Iterable[BaseNode],
         algorithm: utils.Algorithm,
         output_edge_order: Optional[Sequence[Edge]] = None,
         ignore_edge_order: bool = False) -> BaseNode:
  """Base method for all `opt_einsum` contractors.

  Args:
    nodes: A collection of connected nodes.
    algorithm: `opt_einsum` contraction method to use.
    output_edge_order: An optional list of edges. Edges of the
      final node in `nodes_set`
      are reordered into `output_edge_order`;
      if final node has more than one edge,
      `output_edge_order` must be pronvided.
    ignore_edge_order: An option to ignore the output edge
      order.

  Returns:
    Final node after full contraction.
  """
  nodes_set = set(nodes)
  edges = get_all_edges(nodes_set)
  #output edge order has to be determinded before any contraction
  #(edges are refreshed after contractions)

  if not ignore_edge_order:
    if output_edge_order is None:
      output_edge_order = list(get_subgraph_dangling(nodes))
      if len(output_edge_order) > 1:
        raise ValueError("The final node after contraction has more than "
                         "one remaining edge. In this case `output_edge_order` "
                         "has to be provided.")

    if set(output_edge_order) != get_subgraph_dangling(nodes):
      raise ValueError("output edges are not equal to the remaining "
                       "non-contracted edges of the final node.")

  for edge in edges:
    if not edge.is_disabled:  #if its disabled we already contracted it
      if edge.is_trace():
        nodes_set.remove(edge.node1)
        nodes_set.add(contract_parallel(edge))

  if len(nodes_set) == 1:
    # There's nothing to contract.
    if ignore_edge_order:
      return list(nodes_set)[0]
    return list(nodes_set)[0].reorder_edges(output_edge_order)

  # Then apply `opt_einsum`'s algorithm
  path, nodes = utils.get_path(nodes_set, algorithm)
  for a, b in path:
    new_node = contract_between(nodes[a], nodes[b], allow_outer_product=True)
    nodes.append(new_node)
    nodes = utils.multi_remove(nodes, [a, b])

  # if the final node has more than one edge,
  # output_edge_order has to be specified
  final_node = nodes[0]  # nodes were connected, we checked this
  if not ignore_edge_order:
    final_node.reorder_edges(output_edge_order)
  return final_node


def optimal(nodes: Iterable[BaseNode],
            output_edge_order: Optional[Sequence[Edge]] = None,
            memory_limit: Optional[int] = None,
            ignore_edge_order: bool = False) -> BaseNode:
  """Optimal contraction order via `opt_einsum`.

  This method will find the truly optimal contraction order via
  `opt_einsum`'s depth first search algorithm. Since this search is
  exhaustive, if your network is large (n>10), then the search may
  take longer than just contracting in a suboptimal way.

  Args:
    nodes: an iterable of Nodes
    output_edge_order: An optional list of edges.
      Edges of the final node in `nodes_set`
      are reordered into `output_edge_order`;
      if final node has more than one edge,
      `output_edge_order` must be provided.
    memory_limit: Maximum number of elements in an array during contractions.
    ignore_edge_order: An option to ignore the output edge order.

  Returns:
    The final node after full contraction.
  """
  alg = functools.partial(opt_einsum.paths.optimal, memory_limit=memory_limit)
  return base(nodes, alg, output_edge_order, ignore_edge_order)


def branch(nodes: Iterable[BaseNode],
           output_edge_order: Optional[Sequence[Edge]] = None,
           memory_limit: Optional[int] = None,
           nbranch: Optional[int] = None,
           ignore_edge_order: bool = False) -> BaseNode:
  """Branch contraction path via `opt_einsum`.

  This method uses the DFS approach of `optimal` while sorting potential
  contractions based on a heuristic cost, in order to reduce time spent
  in exploring paths which are unlikely to be optimal.
  More details on `branching path`_.

  .. _branching path:
    https://optimized-einsum.readthedocs.io/en/latest/branching_path.html

  Args:
    nodes: an iterable of Nodes
    output_edge_order: An optional list of edges.
      Edges of the final node in `nodes_set`
      are reordered into `output_edge_order`;
      if final node has more than one edge,
      `output_edge_order` must be provided.
    memory_limit: Maximum number of elements in an array during contractions.
    nbranch: Number of best contractions to explore.
      If None it explores all inner products starting with those that
      have the best cost heuristic.
    ignore_edge_order: An option to ignore the output edge order.

  Returns:
    The final node after full contraction.
  """
  alg = functools.partial(
      opt_einsum.paths.branch, memory_limit=memory_limit, nbranch=nbranch)
  return base(nodes, alg, output_edge_order, ignore_edge_order)


def greedy(nodes: Iterable[BaseNode],
           output_edge_order: Optional[Sequence[Edge]] = None,
           memory_limit: Optional[int] = None,
           ignore_edge_order: bool = False) -> BaseNode:
  """Greedy contraction path via `opt_einsum`.

  This provides a more efficient strategy than `optimal` for finding
  contraction paths in large networks. First contracts pairs of tensors
  by finding the pair with the lowest cost at each step. Then it performs
  the outer products. More details on `greedy path`_.

  ..  _greedy path:
    https://optimized-einsum.readthedocs.io/en/latest/greedy_path.html

  Args:
    nodes: an iterable of Nodes
    output_edge_order: An optional list of edges.
      Edges of the final node in `nodes_set`
      are reordered into `output_edge_order`;
      if final node has more than one edge,
      `output_edge_order` must be provided.
    memory_limit: Maximum number of elements in an array during contractions.
    ignore_edge_order: An option to ignore the output edge order.

  Returns:
    The final node after full contraction.
  """
  alg = functools.partial(opt_einsum.paths.greedy, memory_limit=memory_limit)
  return base(nodes, alg, output_edge_order, ignore_edge_order)


# pylint: disable=too-many-return-statements
def auto(nodes: Iterable[BaseNode],
         output_edge_order: Optional[Sequence[Edge]] = None,
         memory_limit: Optional[int] = None,
         ignore_edge_order: bool = False) -> BaseNode:
  """Chooses one of the above algorithms according to network size.

  Default behavior is based on `opt_einsum`'s `auto` contractor.

  Args:
    nodes: A collection of connected nodes.
    output_edge_order: An optional list of edges.
      Edges of the final node in `nodes_set`
      are reordered into `output_edge_order`;
      if final node has more than one edge,
      `output_edge_order` must be provided.
    memory_limit: Maximum number of elements in an array during contractions.
    ignore_edge_order: An option to ignore the output edge order.

  Returns:
    Final node after full contraction.
  """

  n = len(list(nodes))  #pytype thing
  _nodes = nodes
  if n <= 0:
    raise ValueError("Cannot contract empty tensor network.")
  if n == 1:
    if not ignore_edge_order:
      if output_edge_order is None:
        output_edge_order = list(
            (get_all_edges(_nodes) - get_all_nondangling(_nodes)))
        if len(output_edge_order) > 1:
          raise ValueError(
              "The final node after contraction has more than "
              "one dangling edge. In this case `output_edge_order` "
              "has to be provided.")

    edges = get_all_nondangling(_nodes)
    if edges:
      final_node = contract_parallel(edges.pop())
    else:
      final_node = list(_nodes)[0]
    final_node.reorder_edges(output_edge_order)
    if not ignore_edge_order:
      final_node.reorder_edges(output_edge_order)
    return final_node

  if n < 5:
    return optimal(nodes, output_edge_order, memory_limit, ignore_edge_order)
  if n < 7:
    return branch(nodes, output_edge_order, memory_limit, ignore_edge_order)
  if n < 9:
    return branch(
        nodes,
        output_edge_order,
        memory_limit,
        nbranch=2,
        ignore_edge_order=ignore_edge_order)
  if n < 15:
    return branch(
        nodes,
        output_edge_order,
        nbranch=1,
        ignore_edge_order=ignore_edge_order)
  return greedy(nodes, output_edge_order, memory_limit, ignore_edge_order)


def custom(nodes: Iterable[BaseNode],
           optimizer: Any,
           output_edge_order: Sequence[Edge] = None,
           memory_limit: Optional[int] = None,
           ignore_edge_order: bool = False) -> BaseNode:
  """Uses a custom path optimizer created by the user to calculate paths.

  The custom path optimizer should inherit `opt_einsum`'s `PathOptimizer`.
  See `custom paths`_.

  .. _custom paths:
    https://optimized-einsum.readthedocs.io/en/latest/custom_paths.html

  Args:
    nodes: an iterable of Nodes
    output_edge_order: An optional list of edges.
      Edges of the final node in `nodes_set`
      are reordered into `output_edge_order`;
      if final node has more than one edge,
      output_edge_order` must be provided.
    optimizer: A custom `opt_einsum.PathOptimizer` object.
    memory_limit: Maximum number of elements in an array during contractions.
    ignore_edge_order: An option to ignore the output edge order.

  Returns:
    Final node after full contraction.
  """
  alg = functools.partial(optimizer, memory_limit=memory_limit)
  return base(nodes, alg, output_edge_order, ignore_edge_order)
