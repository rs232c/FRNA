"""
Deployment script for website
"""
import os
import shutil
import logging
from config import WEBSITE_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class WebsiteDeployer:
    """Handle website deployment to various platforms"""
    
    def __init__(self):
        self.output_dir = WEBSITE_CONFIG.get("output_dir", "website_output")
        self.deploy_method = WEBSITE_CONFIG.get("deploy_method", "github_pages")
    
    def deploy_to_github_pages(self):
        """Deploy to GitHub Pages"""
        logger.info("Deploying to GitHub Pages...")
        
        # Check if git is initialized
        if not os.path.exists(".git"):
            logger.error("Git repository not initialized. Run 'git init' first.")
            return False
        
        # Check if website_output exists
        if not os.path.exists(self.output_dir):
            logger.error(f"Website output directory {self.output_dir} not found")
            return False
        
        try:
            # Add and commit changes
            import subprocess
            subprocess.run(["git", "add", self.output_dir], check=True)
            subprocess.run(["git", "commit", "-m", "Update website"], check=True)
            subprocess.run(["git", "push"], check=True)
            
            logger.info("Website deployed to GitHub Pages")
            logger.info("Note: Enable GitHub Pages in repository settings")
            return True
        
        except subprocess.CalledProcessError as e:
            logger.error(f"Git deployment failed: {e}")
            return False
        except FileNotFoundError:
            logger.error("Git not found. Please install Git to deploy.")
            return False
    
    def deploy_to_netlify(self):
        """Deploy to Netlify (requires Netlify CLI)"""
        logger.info("Deploying to Netlify...")
        
        if not os.path.exists(self.output_dir):
            logger.error(f"Website output directory {self.output_dir} not found")
            return False
        
        try:
            import subprocess
            # Netlify CLI deployment
            result = subprocess.run(
                ["netlify", "deploy", "--dir", self.output_dir, "--prod"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                logger.info("Website deployed to Netlify")
                return True
            else:
                logger.error(f"Netlify deployment failed: {result.stderr}")
                return False
        
        except FileNotFoundError:
            logger.error("Netlify CLI not found. Install with: npm install -g netlify-cli")
            return False
    
    def deploy_to_vercel(self):
        """Deploy to Vercel (requires Vercel CLI)"""
        logger.info("Deploying to Vercel...")
        
        if not os.path.exists(self.output_dir):
            logger.error(f"Website output directory {self.output_dir} not found")
            return False
        
        try:
            import subprocess
            # Change to output directory and deploy
            result = subprocess.run(
                ["vercel", "--cwd", self.output_dir, "--prod"],
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                logger.info("Website deployed to Vercel")
                return True
            else:
                logger.error(f"Vercel deployment failed: {result.stderr}")
                return False
        
        except FileNotFoundError:
            logger.error("Vercel CLI not found. Install with: npm install -g vercel")
            return False
    
    def deploy(self):
        """Deploy using configured method"""
        if self.deploy_method == "github_pages":
            return self.deploy_to_github_pages()
        elif self.deploy_method == "netlify":
            return self.deploy_to_netlify()
        elif self.deploy_method == "vercel":
            return self.deploy_to_vercel()
        else:
            logger.warning(f"Unknown deploy method: {self.deploy_method}")
            logger.info("Website files are ready in {self.output_dir} for manual deployment")
            return False


if __name__ == "__main__":
    deployer = WebsiteDeployer()
    deployer.deploy()

