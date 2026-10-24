from dotenv import load_dotenv

load_dotenv()

from app.ai.huggingface_analyzer import HuggingFaceAnalyzer


test_files = [
    {
        "name": "Krinal_Resume_2026.pdf",
        "relative_path": "Krinal_Resume_2026.pdf",
        "extension": ".pdf",
        "category": "documents",
        "size": 245000
    },
    {
        "name": "AWS_Certification_Notes.pdf",
        "relative_path": "AWS_Certification_Notes.pdf",
        "extension": ".pdf",
        "category": "documents",
        "size": 1800000
    },
    {
        "name": "IMG_9283.jpg",
        "relative_path": "IMG_9283.jpg",
        "extension": ".jpg",
        "category": "images",
        "size": 4200000
    },
    {
        "name": "vacation_beach.jpg",
        "relative_path": "vacation_beach.jpg",
        "extension": ".jpg",
        "category": "images",
        "size": 3200000
    },
    {
        "name": "ChromeSetup.exe",
        "relative_path": "ChromeSetup.exe",
        "extension": ".exe",
        "category": "executables",
        "size": 120000000
    },
    {
        "name": "project_backup.zip",
        "relative_path": "project_backup.zip",
        "extension": ".zip",
        "category": "archives",
        "size": 850000000
    },
    {
        "name": "invoice_August_2026.pdf",
        "relative_path": "Old Downloads/invoice_August_2026.pdf",
        "extension": ".pdf",
        "category": "documents",
        "size": 650000
    },
    {
        "name": "asdf_8392.dat",
        "relative_path": "asdf_8392.dat",
        "extension": ".dat",
        "category": "unknown",
        "size": 12000
    }
]


analyzer = HuggingFaceAnalyzer()

result = analyzer.analyze(test_files)

print("\nAI CLEANUP PLAN")
print("=" * 60)

for analysis in result.analyses:
    print(f"\nFile: {analysis.relative_path}")
    print(f"Category: {analysis.category}")
    print(f"Subcategory: {analysis.subcategory}")
    print(f"Action: {analysis.action}")
    print(f"Destination: {analysis.destination}")
    print(f"Confidence: {analysis.confidence}")
    print(f"Reason: {analysis.reason}")