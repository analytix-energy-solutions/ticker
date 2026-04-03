/**
 * Ticker Conditions Tree - Pure Data Helpers
 * Tree manipulation functions for condition groups (AND/OR nesting).
 *
 * No DOM access. All functions return new tree objects (immutable pattern).
 * Path convention: array of child indices, e.g. [0, 1] = tree.children[0].children[1].
 *
 * Maximum nesting depth is 2 (root → child group → grandchild group → leaves).
 */
window.Ticker = window.Ticker || {};

window.Ticker.conditionsTree = {
  /** Maximum allowed nesting depth. */
  MAX_DEPTH: 2,

  /**
   * Create an empty root group.
   * @param {string} operator - 'AND' or 'OR'
   * @returns {object} Root group node
   */
  createRoot(operator) {
    return { type: 'group', operator: operator || 'AND', children: [] };
  },

  /**
   * Deep clone a tree node.
   * @param {object} node - Tree node to clone
   * @returns {object} Deep copy
   */
  clone(node) {
    return JSON.parse(JSON.stringify(node));
  },

  /**
   * Get a node at a given path.
   * @param {object} tree - Root tree node
   * @param {number[]} path - Array of child indices
   * @returns {object|null} The node, or null if path is invalid
   */
  getNode(tree, path) {
    let node = tree;
    for (const idx of path) {
      if (!node.children || idx < 0 || idx >= node.children.length) return null;
      node = node.children[idx];
    }
    return node;
  },

  /**
   * Toggle a group's operator between AND and OR.
   * @param {object} tree - Root tree
   * @param {number[]} path - Path to the group node
   * @returns {object} New tree with toggled operator
   */
  toggleOperator(tree, path) {
    const cloned = this.clone(tree);
    const node = this.getNode(cloned, path);
    if (node && node.type === 'group') {
      node.operator = node.operator === 'AND' ? 'OR' : 'AND';
    }
    return cloned;
  },

  /**
   * Group two adjacent children into a new sub-group.
   * The new sub-group inherits the parent's current operator.
   * Respects MAX_DEPTH: returns unchanged tree if depth would be exceeded.
   * @param {object} tree - Root tree
   * @param {number[]} parentPath - Path to the parent group
   * @param {number} index - Index of the first child to group
   * @returns {object} New tree with the two children wrapped in a sub-group
   */
  groupNodes(tree, parentPath, index) {
    const cloned = this.clone(tree);
    const parent = this.getNode(cloned, parentPath);
    if (!parent || !parent.children || index + 1 >= parent.children.length) {
      return cloned;
    }
    // Depth check: parentPath.length is current depth, new group adds 1
    if (parentPath.length + 1 > this.MAX_DEPTH) return cloned;
    const child1 = parent.children[index];
    const child2 = parent.children[index + 1];
    const newGroup = { type: 'group', operator: parent.operator, children: [child1, child2] };
    parent.children.splice(index, 2, newGroup);
    return cloned;
  },

  /**
   * Ungroup: flatten a group's children back into the parent.
   * @param {object} tree - Root tree
   * @param {number[]} parentPath - Path to the parent that contains the group
   * @param {number} index - Index of the group within the parent's children
   * @returns {object} New tree with the group's children inlined
   */
  ungroupGroup(tree, parentPath, index) {
    const cloned = this.clone(tree);
    const parent = this.getNode(cloned, parentPath);
    if (!parent || !parent.children || index >= parent.children.length) {
      return cloned;
    }
    const group = parent.children[index];
    if (group.type !== 'group') return cloned;
    parent.children.splice(index, 1, ...group.children);
    return cloned;
  },

  /**
   * Remove a node at a specific index within a parent.
   * @param {object} tree - Root tree
   * @param {number[]} parentPath - Path to the parent group
   * @param {number} index - Index of the child to remove
   * @returns {object} New tree with the node removed
   */
  removeNode(tree, parentPath, index) {
    const cloned = this.clone(tree);
    const parent = this.getNode(cloned, parentPath);
    if (!parent || !parent.children || index < 0 || index >= parent.children.length) {
      return cloned;
    }
    parent.children.splice(index, 1);
    return cloned;
  },

  /**
   * Add a leaf node to the root group's children.
   * @param {object} tree - Root tree
   * @param {object} leaf - Leaf node to add (e.g. { type: 'zone', zone_id: '...' })
   * @returns {object} New tree with the leaf appended
   */
  addLeaf(tree, leaf) {
    const cloned = this.clone(tree);
    cloned.children.push(JSON.parse(JSON.stringify(leaf)));
    return cloned;
  },

  /**
   * Add a leaf node to a specific group within the tree.
   * @param {object} tree - Root tree
   * @param {number[]} parentPath - Path to the target group
   * @param {object} leaf - Leaf node to add
   * @returns {object} New tree with the leaf appended to the target group
   */
  addLeafAt(tree, parentPath, leaf) {
    const cloned = this.clone(tree);
    const parent = this.getNode(cloned, parentPath);
    if (!parent || parent.type !== 'group') return cloned;
    parent.children.push(JSON.parse(JSON.stringify(leaf)));
    return cloned;
  },

  /**
   * Get the maximum depth of the tree.
   * A single root group with only leaves has depth 0.
   * @param {object} node - Tree node
   * @param {number} depth - Current depth (used for recursion)
   * @returns {number} Maximum depth
   */
  getMaxDepth(node, depth) {
    if (typeof depth === 'undefined') depth = 0;
    if (node.type !== 'group' || !node.children) return depth;
    let max = depth;
    for (const child of node.children) {
      const d = this.getMaxDepth(child, depth + 1);
      if (d > max) max = d;
    }
    return max;
  },

  /**
   * Check if a tree has at least one leaf node.
   * @param {object} node - Tree node
   * @returns {boolean} True if the tree contains at least one leaf
   */
  hasLeaves(node) {
    if (node.type !== 'group') return true;
    if (!node.children || node.children.length === 0) return false;
    return node.children.some(function(c) { return window.Ticker.conditionsTree.hasLeaves(c); });
  },

  /**
   * Collect all leaf nodes from a tree into a flat array.
   * @param {object} node - Tree node
   * @returns {object[]} Array of leaf nodes
   */
  collectLeaves(node) {
    if (node.type !== 'group') return [node];
    var leaves = [];
    var children = node.children || [];
    for (var i = 0; i < children.length; i++) {
      var childLeaves = window.Ticker.conditionsTree.collectLeaves(children[i]);
      for (var j = 0; j < childLeaves.length; j++) {
        leaves.push(childLeaves[j]);
      }
    }
    return leaves;
  },

  /**
   * Count all nodes in the tree (groups + leaves).
   * @param {object} node - Tree node
   * @returns {number} Total node count
   */
  countNodes(node) {
    if (node.type !== 'group' || !node.children) return 1;
    let count = 1;
    for (const child of node.children) {
      count += this.countNodes(child);
    }
    return count;
  },

  /**
   * Wrap a flat rules array into a root AND group.
   * Migration helper for converting old flat conditions to tree format.
   * @param {object[]} rules - Array of leaf rule objects
   * @returns {object} Root group containing the rules as children
   */
  fromFlatRules(rules) {
    return {
      type: 'group',
      operator: 'AND',
      children: Array.isArray(rules) ? rules.map(function(r) { return JSON.parse(JSON.stringify(r)); }) : [],
    };
  },

  /**
   * Extract a flat rules array from a tree (inverse of fromFlatRules).
   * Only collects leaf nodes, discarding group structure.
   * @param {object} tree - Root tree node
   * @returns {object[]} Flat array of leaf rules
   */
  toFlatRules(tree) {
    return this.collectLeaves(tree);
  },

  /**
   * Remove incomplete leaf nodes from a condition tree.
   * Returns a new tree with only valid leaves retained.
   * @param {object} node - Tree node
   * @returns {object|null} Pruned tree, or null if nothing valid remains
   */
  pruneTree(node) {
    if (!node) return null;
    if (node.type !== 'group') {
      // Leaf: validate required fields per type
      if (!node.type) return null;
      if (node.type === 'zone' && !node.zone_id) return null;
      if (node.type === 'time' && (!node.after || !node.before)) return null;
      if (node.type === 'state' && (!node.entity_id || !node.state)) return null;
      return node;
    }
    var self = this;
    var pruned = (node.children || []).map(function(c) { return self.pruneTree(c); }).filter(Boolean);
    if (pruned.length === 0) return null;
    return { type: node.type, operator: node.operator, children: pruned };
  },

  /**
   * Validate that a tree respects the MAX_DEPTH constraint.
   * @param {object} tree - Root tree node
   * @returns {boolean} True if the tree depth is within limits
   */
  isValidDepth(tree) {
    return this.getMaxDepth(tree) <= this.MAX_DEPTH;
  },
};
