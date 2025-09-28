# README.md

# Legal Document Pseudonymizer

A professional-grade document pseudonymization tool designed specifically for law firms and legal departments. This application allows lawyers to safely anonymize sensitive legal documents while maintaining document structure and legal context.

## 🌟 Key Features

### For Lawyers (Simple Interface)
- **Drag & Drop Upload**: Support for TXT, DOCX, and PDF files
- **Side-by-Side Comparison**: View original vs pseudonymized content
- **One-Click Processing**: Simple, intuitive workflow
- **Instant Download**: Get processed documents immediately
- **Legal-Specific**: Understands case numbers, legal citations, court addresses

### For IT/Compliance (Enterprise Features)
- **Audit Logging**: Complete trail of all processing activities
- **Role-Based Access**: Support for different user roles and permissions
- **Compliance Standards**: GDPR, HIPAA, Singapore PDPA support
- **Quality Metrics**: Processing statistics and confidence scores
- **Session Management**: Secure, isolated user sessions

## 🔒 What Gets Pseudonymized

| Entity Type | Original | Becomes |
|-------------|----------|---------|
| **People** | John Smith | Person A |
| **Organizations** | ABC Corp | Company A |
| **Addresses** | 123 Main St, Singapore | Location A |
| **Phone Numbers** | +65 9123 4567 | +XX XXXX XXXX |
| **Email Addresses** | john@abc.com | emailA@[REDACTED].com |
| **Money Amounts** | $500,000 | [REDACTED AMOUNT] |
| **Dates** | 15 January 2024 | 23 March 2022 |
| **Case Numbers** | HC/S 123/2024 | Case No. [REDACTED-1] |
| **Legal Citations** | [2024] 1 SLR 123 | [LEGAL CITATION REDACTED] |

## 🚀 Quick Start

1. **Install Python 3.8+**

2. **Clone or download the application files:**
   - `pseudonymizer_app.py` (main Streamlit interface)
   - `pseudonymscript.py` (enterprise pseudonymization engine)
   - `requirements.txt` (dependencies)

3. **Run the launcher:**
   ```bash
   python run_app.py
   ```
   
   Or manually:
   ```bash
   pip install -r requirements.txt
   python -m spacy download en_core_web_sm
   streamlit run pseudonymizer_app.py
   ```

4. **Open your browser** to `http://localhost:8501`

5. **Upload a document** and click "Process Document"

6. **Review** the side-by-side comparison

7. **Download** your pseudonymized document

## 📱 User Interface

### Main Screen
```
⚖️ Legal Document Pseudonymizer
┌─────────────────────────────────────────┐
│  📁 Upload Your Document                │
│  [Choose file: TXT, DOCX, PDF]         │
│                                         │
│  [🔒 Process Document]                  │
└─────────────────────────────────────────┘
```

### Results View
```
📊 Processing Stats    🔄 Replacements    ⏱️ Time    ✅ Quality
   15 entities            12 made         0.8s       95%

┌─────────────────┬─────────────────────┐
│ 📄 Original     │ 🔒 Pseudonymized   │
│                 │                     │
│ John Smith      │ Person A            │
│ signed contract │ signed contract     │
│ with ABC Corp   │ with Company A      │
│ on 15 Jan 2024  │ on 23 Mar 2022      │
└─────────────────┴─────────────────────┘

💾 [Download Document] [Download Mapping] [Download Report]
```

## ⚙️ Configuration Options

### Sidebar Settings
- **User Information**: Email and firm name for audit logs
- **Compliance Standard**: GDPR, HIPAA, Singapore PDPA, General
- **Processing Options**: Formatting preservation, entity type display
- **Help Sections**: Usage guide, entity types, compliance info

### Advanced Configuration (for IT)
```python
config = EnterpriseConfig(
    # Security
    enable_audit_log=True,
    require_user_auth=True,
    max_document_size_mb=50,
    
    # Compliance
    compliance_standard=ComplianceStandard.SINGAPORE_PDPA,
    retention_days=2555,  # 7 years
    
    # Performance
    batch_size=1000,
    max_concurrent_jobs=4,
    cache_mappings=True
)
```

## 🔐 Security & Privacy

- **Local Processing Only**: No data sent to external servers
- **Session Isolation**: Each user session is completely separate
- **Automatic Cleanup**: Sessions expire and data is cleaned
- **Audit Trail**: Complete logging of all activities
- **No Persistent Storage**: Original documents are not saved

## 🏢 Enterprise Deployment

### For Company Intranet
The tool includes a `WebAPIWrapper` class for integration with existing intranet systems:

```python
# Web API integration
api = WebAPIWrapper(EnterpriseConfig(...))
session_id = api.create_user_session(user_id, user_role, ip_address)
result = api.process_document_api(session_id, content, filename)
```

### Database Schema
Audit logs are stored in SQLite with the following structure:
- `audit_logs`: User activities, timestamps, compliance info
- `entity_mappings`: Pseudonymization mappings (session-scoped)

### Compliance Reports
Automatic generation of compliance documentation including:
- Processing statistics and quality metrics
- Entity mapping tables (downloadable)
- Audit trail summaries
- Data retention and deletion schedules

## 🛠️ Customization

### Adding New Entity Types
```python
# In pseudonymscript.py
def _generate_replacement_by_type(self, label: str, original: str, counters: Dict[str, int]) -> str:
    if label == "CUSTOM_ENTITY":
        counters["CUSTOM_ENTITY"] += 1
        return f"Custom {counters['CUSTOM_ENTITY']}"
```

### Custom Regex Patterns
```python
# Add to _initialize_patterns()
'custom_pattern': re.compile(r'your_regex_here', re.IGNORECASE)
```

### Styling Customization
The Streamlit app includes extensive CSS customization in the `st.markdown()` sections.

## 📋 Compliance Standards

### GDPR
- Article 6 basis: Legitimate interest
- Data subject rights applicable
- 7-year retention by default
- Right to deletion supported

### Singapore PDPA
- Deemed consent handling
- Local processing compliance
- Data breach notification ready
- Individual access rights

### HIPAA
- Safe harbor method compliance
- Audit trail requirements
- Access control logging
- Data integrity measures

## 🔧 Troubleshooting

### Common Issues

**"spaCy model not found"**
```bash
python -m spacy download en_core_web_sm
```

**PDF processing fails**
```bash
pip install pymupdf pdfminer.six
```

**Large file memory issues**
- Reduce `max_document_size_mb` in config
- Process files in smaller chunks

**Streamlit won't start**
- Check Python version (3.8+ required)
- Verify all dependencies installed
- Check firewall settings for port 8501

### Performance Optimization

For large documents:
1. Increase `batch_size` in configuration
2. Enable `cache_mappings` for repeated processing
3. Use `max_concurrent_jobs` for batch processing
4. Consider upgrading to larger spaCy models for better accuracy

## 📞 Support

For technical support or feature requests:
1. Check the troubleshooting section above
2. Review logs in the `logs/` directory
3. Check audit database for processing history
4. Contact your IT administrator for enterprise features

## 🚀 Future Roadmap

- [ ] Support for additional file formats (ODT, RTF)
- [ ] Batch processing interface
- [ ] Integration with popular DMS systems
- [ ] Advanced entity recognition for legal terms
- [ ] Multi-language support
- [ ] Cloud deployment options
- [ ] Advanced analytics dashboard
- [ ] API rate limiting and quotas
