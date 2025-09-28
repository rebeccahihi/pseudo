# run_app.py
# Simple launcher script for the Streamlit app

import subprocess
import sys
import os
from pathlib import Path

def check_dependencies():
    """Check if required packages are installed."""
    required_packages = [
        'streamlit', 'pandas', 'spacy', 'docx', 'PyPDF2', 'pdfplumber'
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            if package == 'docx':
                import docx
            elif package == 'PyPDF2':
                import PyPDF2
            else:
                __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    return missing_packages

def check_spacy_model():
    """Check if spaCy English model is installed."""
    try:
        import spacy
        nlp = spacy.load("en_core_web_sm")
        return True
    except OSError:
        return False

def main():
    """Main launcher function."""
    print("🚀 Legal Document Pseudonymizer Launcher")
    print("=" * 50)
    
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8+ is required. Current version:", sys.version)
        sys.exit(1)
    
    print("✅ Python version:", sys.version.split()[0])
    
    # Check dependencies
    print("\n📦 Checking dependencies...")
    missing_packages = check_dependencies()
    
    if missing_packages:
        print("❌ Missing packages:", ", ".join(missing_packages))
        print("\n🔧 To install missing packages, run:")
        print("   pip install -r requirements.txt")
        
        install = input("\n❓ Install missing packages now? (y/n): ").lower()
        if install == 'y':
            print("📥 Installing packages...")
            subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        else:
            print("❌ Cannot run without required packages.")
            sys.exit(1)
    else:
        print("✅ All packages installed")
    
    # Check spaCy model
    print("\n🧠 Checking spaCy model...")
    if not check_spacy_model():
        print("❌ spaCy English model not found")
        print("\n🔧 To install spaCy model, run:")
        print("   python -m spacy download en_core_web_sm")
        
        install_model = input("\n❓ Install spaCy model now? (y/n): ").lower()
        if install_model == 'y':
            print("📥 Installing spaCy model...")
            subprocess.run([sys.executable, "-m", "spacy", "download", "en_core_web_sm"])
        else:
            print("❌ Cannot run without spaCy model.")
            sys.exit(1)
    else:
        print("✅ spaCy model available")
    
    # Check if main app file exists
    app_file = Path("pseudonymizer_app.py")
    if not app_file.exists():
        print("❌ Main application file 'pseudonymizer_app.py' not found")
        sys.exit(1)
    
    # Create necessary directories
    Path("logs").mkdir(exist_ok=True)
    
    print("\n🎉 All checks passed!")
    print("\n🌐 Starting Streamlit application...")
    print("   The app will open in your default browser")
    print("   Press Ctrl+C to stop the application")
    print("=" * 50)
    
    # Launch Streamlit
    try:
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", "pseudonymizer_app.py",
            "--server.headless", "false",
            "--server.port", "8501",
            "--browser.gatherUsageStats", "false"
        ])
    except KeyboardInterrupt:
        print("\n\n👋 Application stopped by user")
    except Exception as e:
        print(f"\n❌ Error running application: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
