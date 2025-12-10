"""
Website generator package
Modular structure matching backend organization
"""
# Import from the parent directory's website_generator.py module
# This maintains backward compatibility while we migrate to the new structure
import sys
from pathlib import Path

_package_dir = Path(__file__).parent
_parent_dir = _package_dir.parent

# Import from the module file in parent directory
# We need to import it as a module, not as a package
import importlib.util
spec = importlib.util.spec_from_file_location("website_generator_module", _parent_dir / "website_generator.py")
website_generator_module = importlib.util.module_from_spec(spec)
sys.modules["website_generator_module"] = website_generator_module
spec.loader.exec_module(website_generator_module)

WebsiteGenerator = website_generator_module.WebsiteGenerator

__all__ = ['WebsiteGenerator']
