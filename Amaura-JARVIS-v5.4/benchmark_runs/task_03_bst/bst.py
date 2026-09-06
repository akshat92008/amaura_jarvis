class BinarySearchTree:
    def __init__(self):
        self.root = None

    class Node:
        def __init__(self, val):
            self.val = val
            self.left = None
            self.right = None

    def insert(self, val: int) -> None:
        if not self.root:
            self.root = self.Node(val)
            return

        current = self.root
        while True:
            if val < current.val:
                if current.left is None:
                    current.left = self.Node(val)
                    break
                else:
                    current = current.left
            elif val > current.val:
                if current.right is None:
                    current.right = self.Node(val)
                    break
                else:
                    current = current.right
            else:
                # Value already exists in the tree
                break

    def contains(self, val: int) -> bool:
        current = self.root
        while current:
            if val == current.val:
                return True
            elif val < current.val:
                current = current.left
            else:
                current = current.right
        return False

    def inorder(self) -> list[int]:
        result = []
        
        def traverse(node):
            if node:
                traverse(node.left)
                result.append(node.val)
                traverse(node.right)

        traverse(self.root)
        return result