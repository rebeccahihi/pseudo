"""
Simple Legal Document Pseudonymizer
==================================

Clean, minimal interface for lawyers to pseudonymize documents.
Supports TXT, DOCX, and PDF files.

Usage: streamlit run pseudonymizer_app.py
"""

import streamlit as st
import pandas as pd
from pathlib import Path
import json
import time
from io import BytesIO

# Document processing imports
import docx
import PyPDF2
import pdfplumber
from docx import Document

# PDF generation
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

# Import our updated pseudonymization tool
from pseudonymscript import PseudonymizationPipeline, PseudonymConfig, pseudonymize_text

# Simple page config
st.set_page_config(
    page_title="Document Pseudonymizer",
    page_icon="🔒",
    layout="wide"
)


class DocumentProcessor:
    """Handle different document formats."""
    
    @staticmethod
    def extract_text_from_txt(file) -> str:
        try:
            return file.read().decode('utf-8')
        except UnicodeDecodeError:
            file.seek(0)
            for encoding in ['utf-8', 'latin-1', 'cp1252']:
                try:
                    file.seek(0)
                    return file.read().decode(encoding)
                except UnicodeDecodeError:
                    continue
            raise ValueError("Could not decode text file")
    
    @staticmethod
    def extract_text_from_docx(file) -> str:
        doc = Document(file)
        full_text = []
        
        for paragraph in doc.paragraphs:
            full_text.append(paragraph.text)
        
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    full_text.append(cell.text)
        
        return '\n'.join(full_text)
    
    @staticmethod
    def extract_text_from_pdf(file) -> str:
        text_content = []
        
        try:
            with pdfplumber.open(file) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_content.append(text)
        except Exception:
            file.seek(0)
            pdf_reader = PyPDF2.PdfReader(file)
            for page in pdf_reader.pages:
                text_content.append(page.extract_text())
        
        return '\n'.join(text_content)
    
    @classmethod
    def process_file(cls, uploaded_file) -> tuple[str, str]:
        file_extension = Path(uploaded_file.name).suffix.lower()
        
        if file_extension == '.txt':
            content = cls.extract_text_from_txt(uploaded_file)
        elif file_extension == '.docx':
            content = cls.extract_text_from_docx(uploaded_file)
        elif file_extension == '.pdf':
            content = cls.extract_text_from_pdf(uploaded_file)
        else:
            raise ValueError(f"Unsupported file type: {file_extension}")
        
        return content, uploaded_file.name


def create_pdf(content: str, filename: str) -> BytesIO:
    """Create a PDF from text content"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                           topMargin=72, bottomMargin=18)
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=30,
    )
    normal_style = styles['Normal']
    normal_style.fontSize = 10
    normal_style.leading = 12
    
    # Build story
    story = []
    
    # Title
    title = Paragraph(f"Pseudonymized Document: {filename}", title_style)
    story.append(title)
    story.append(Spacer(1, 12))
    
    # Content - split into paragraphs and handle line breaks
    paragraphs = content.split('\n\n')
    for para in paragraphs:
        if para.strip():
            # Replace line breaks within paragraphs with spaces
            cleaned_para = para.replace('\n', ' ').strip()
            if cleaned_para:
                p = Paragraph(cleaned_para, normal_style)
                story.append(p)
                story.append(Spacer(1, 6))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer


def create_mapping_pdf(mapping: dict) -> BytesIO:
    """Create a PDF from mapping data"""
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=72, leftMargin=72,
                           topMargin=72, bottomMargin=18)
    
    # Styles
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        spaceAfter=30,
    )
    normal_style = styles['Normal']
    normal_style.fontSize = 10
    normal_style.leading = 12
    
    # Build story
    story = []
    
    # Title
    title = Paragraph("Entity Replacement Mapping", title_style)
    story.append(title)
    story.append(Spacer(1, 12))
    
    # Add mapping entries
    for original, replacement in mapping.items():
        entry = Paragraph(f"<b>{original}</b> → {replacement}", normal_style)
        story.append(entry)
        story.append(Spacer(1, 6))
    
    # Build PDF
    doc.build(story)
    buffer.seek(0)
    return buffer


def init_session():
    """Initialize session state."""
    if 'original_content' not in st.session_state:
        st.session_state.original_content = ""
    if 'pseudonymized_content' not in st.session_state:
        st.session_state.pseudonymized_content = ""
    if 'replacement_mapping' not in st.session_state:
        st.session_state.replacement_mapping = {}
    if 'filename' not in st.session_state:
        st.session_state.filename = ""
    if 'processing_time' not in st.session_state:
        st.session_state.processing_time = 0.0


def show_user_guide():
    """User guide and overview page"""
    st.title("📖 User Guide")
    
    # Overview section
    st.markdown("## What this tool does")
    st.markdown("""
    The Legal Document Pseudonymizer automatically identifies and replaces sensitive information in legal documents with fictitious but consistent alternatives. This allows you to:
    
    - **Share documents safely** while protecting client confidentiality
    - **Maintain document structure** and readability
    - **Keep consistent references** (e.g., the same person is always "Person A")
    - **Meet compliance requirements** for data privacy
    """)
    
    st.markdown("---")
    
    # How to use section
    st.markdown("## How to Use")
    st.markdown("""
    ### Step 1: Upload Document
    Go to the **Document Processor** tab and upload your file (TXT, DOCX, or PDF)
    
    ### Step 2: Automatic Processing
    The document processes automatically - no button clicking needed!
    
    ### Step 3: Review Results
    Compare original vs. pseudonymized text side-by-side
    
    ### Step 4: Check Entity Mappings
    See exactly what was changed in the mapping table
    
    ### Step 5: Download
    Get your pseudonymized document as PDF or text file
    """)
    
    st.markdown("---")
    
    # Entity types section
    st.markdown("## What Gets Replaced")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 👤 **People**")
        st.markdown("- Names of individuals")
        st.markdown("- **Example:** John Smith → Person A")
        
        st.markdown("### 🏢 **Companies**")
        st.markdown("- Business names and organizations")
        st.markdown("- **Example:** Apple Inc → Company B")
        
        st.markdown("### 🌍 **Places**")
        st.markdown("- Countries, states, cities")
        st.markdown("- **Example:** Singapore → Country A")
    
    with col2:
        st.markdown("### 💰 **Money**")
        st.markdown("- Currency amounts and values")
        st.markdown("- **Example:** USD 1,000,000 → [REDACTED AMOUNT]")
        
        st.markdown("### 📅 **Dates**")
        st.markdown("- Specific dates and deadlines")
        st.markdown("- **Example:** 15 March 2024 → 8 July 2022")
        
        st.markdown("### 📍 **Addresses**")
        st.markdown("- Street addresses and locations")
        st.markdown("- **Example:** 123 Main Street → [ADDRESS A]")
    
    st.markdown("---")
    
    # Sample entity table
    st.markdown("## 📋 Sample Entity Mapping")
    st.markdown("Here's an example of how entities are mapped:")
    
    sample_data = {
        "Type": ["👤 Person", "🏢 Company", "🌍 Country", "💰 Money", "📅 Date", "📍 Address"],
        "Original": [
            "John Smith",
            "Apple Inc",
            "Singapore", 
            "USD 50,000 (Fifty Thousand Dollars)",
            "15 March 2024",
            "123 Marina Bay Street"
        ],
        "Replaced With": [
            "Person A",
            "Company A", 
            "Country A",
            "[REDACTED AMOUNT]",
            "8 July 2022",
            "[ADDRESS A]"
        ]
    }
    
    sample_df = pd.DataFrame(sample_data)
    st.dataframe(sample_df, use_container_width=True, hide_index=True)
    
    st.markdown("---")
    
    # Important notes
    st.markdown("## ⚠️ Important Notes")
    
    st.info("""
    **Consistency:** The same entity will always get the same replacement throughout the document.
    
    **Structure Preserved:** Document formatting, punctuation, and sentence structure remain unchanged.
    
    **Review Required:** Always review the output to ensure sensitive information is properly handled.
    
    **Compliance:** This tool helps with data privacy but doesn't guarantee complete compliance. Legal review is recommended.
    """)


def show_document_processor():
    """Main document processing page"""
    st.title("🔒 Document Processor")
    
    # File upload
    uploaded_file = st.file_uploader(
        "📁 Choose your document",
        type=['txt', 'docx', 'pdf'],
        help="Upload TXT, DOCX, or PDF files"
    )
    
    if uploaded_file is not None:
        try:
            # Process file
            content, filename = DocumentProcessor.process_file(uploaded_file)
            st.session_state.original_content = content
            st.session_state.filename = filename
            
            st.success(f"✅ File loaded: {filename} ({len(content):,} characters)")
            
            # Process document automatically after upload
            with st.spinner("Processing document..."):
                # Create pseudonymization configuration
                config = PseudonymConfig()  # Use default config
                
                # Process document using the simple function interface
                start_time = time.time()
                pseudonymized_content, replacement_mapping = pseudonymize_text(content, config)
                processing_time = time.time() - start_time
                
                # Store results
                st.session_state.pseudonymized_content = pseudonymized_content
                st.session_state.replacement_mapping = replacement_mapping
                st.session_state.processing_time = processing_time
            
            st.success("✅ Document processed successfully!")
                
        except Exception as e:
            st.error(f"❌ Error: {str(e)}")
    
    # Show results if processing is complete
    if st.session_state.replacement_mapping or st.session_state.pseudonymized_content:
        
        st.markdown("---")
        
        # Quick stats
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Entities Found", len(st.session_state.replacement_mapping))
        with col2:
            st.metric("Replacements Made", len(st.session_state.replacement_mapping))
        with col3:
            st.metric("Processing Time", f"{st.session_state.processing_time:.1f}s")
        
        # Side-by-side comparison
        st.markdown("### 📄 Document Comparison")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("**Original**")
            # Editable text area for copying
            original_text = st.text_area(
                "original",
                value=st.session_state.original_content,
                height=400,
                disabled=False,  # Make it editable for copying
                label_visibility="collapsed"
            )
        
        with col2:
            st.markdown("**Pseudonymized**")
            # Editable text area for copying
            pseudo_text = st.text_area(
                "pseudonymized", 
                value=st.session_state.pseudonymized_content,
                height=400,
                disabled=False,  # Make it editable for copying
                label_visibility="collapsed"
            )
        
        # Entity mapping section
        if st.session_state.replacement_mapping:
            st.markdown("---")
            st.markdown("### 🔄 Entity Mapping")
            
            # Create detailed table
            mapping_data = []
            for original, replacement in st.session_state.replacement_mapping.items():
                # Determine entity type based on replacement pattern
                if replacement.startswith("Person"):
                    entity_type = "👤 Person"
                elif replacement.startswith("Company"):
                    entity_type = "🏢 Company"
                elif replacement.startswith("Country"):
                    entity_type = "🌍 Country"
                elif replacement.startswith("State"):
                    entity_type = "🗺️ State"
                elif replacement.startswith("City"):
                    entity_type = "🏙️ City"
                elif replacement.startswith("Building"):
                    entity_type = "🏢 Building"
                elif replacement.startswith("[ADDRESS"):
                    entity_type = "📍 Address"
                elif replacement == "[REDACTED AMOUNT]":
                    entity_type = "💰 Money"
                elif len(replacement.split()) == 3 and replacement.replace(" ", "").replace(",", "").isalnum():
                    entity_type = "📅 Date"
                else:
                    entity_type = "❓ Other"
                
                mapping_data.append({
                    "Type": entity_type,
                    "Original": original,
                    "Replaced With": replacement
                })
            
            # Create DataFrame and display
            df = pd.DataFrame(mapping_data)
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Type": st.column_config.TextColumn("Type", width="small"),
                    "Original": st.column_config.TextColumn("Original Text", width="large"),
                    "Replaced With": st.column_config.TextColumn("Replacement", width="medium")
                }
            )
        
        # Download section
        st.markdown("---")
        st.markdown("### 💾 Download")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Create PDF for pseudonymized document
            pdf_buffer = create_pdf(st.session_state.pseudonymized_content, st.session_state.filename)
            st.download_button(
                label="📄 Download as PDF",
                data=pdf_buffer.getvalue(),
                file_name=f"pseudonymized_{Path(st.session_state.filename).stem}.pdf",
                mime="application/pdf"
            )
        
        with col2:
            # Download as text file
            st.download_button(
                label="📝 Download as Text",
                data=st.session_state.pseudonymized_content,
                file_name=f"pseudonymized_{st.session_state.filename}",
                mime="text/plain"
            )
        
        with col3:
            # Download mapping
            if st.session_state.replacement_mapping:
                mapping_pdf = create_mapping_pdf(st.session_state.replacement_mapping)
                st.download_button(
                    label="📋 Download Mapping PDF",
                    data=mapping_pdf.getvalue(),
                    file_name="entity_mapping.pdf",
                    mime="application/pdf"
                )
            else:
                st.button("📋 No Mapping Available", disabled=True)


def show_entity_mapping_table():
    """Detailed entity mapping table page"""
    st.title("📋 Entity Mapping Table")
    
    if not st.session_state.replacement_mapping:
        st.info("👆 Please process a document first on the **Document Processor** tab to see the entity mappings.")
        return
    
    st.markdown(f"**Document:** {st.session_state.filename}")
    st.markdown(f"**Total Entities Replaced:** {len(st.session_state.replacement_mapping)}")
    
    st.markdown("---")
    
    # Create detailed table with advanced features
    if st.session_state.replacement_mapping:
        # Convert to DataFrame for better display
        mapping_data = []
        for original, replacement in st.session_state.replacement_mapping.items():
            # Try to determine entity type based on replacement pattern
            if replacement.startswith("Person"):
                entity_type = "👤 Person"
            elif replacement.startswith("Company"):
                entity_type = "🏢 Company"
            elif replacement.startswith("Country"):
                entity_type = "🌍 Country"
            elif replacement.startswith("State"):
                entity_type = "🗺️ State"
            elif replacement.startswith("City"):
                entity_type = "🏙️ City"
            elif replacement.startswith("Building"):
                entity_type = "🏢 Building"
            elif replacement.startswith("[ADDRESS"):
                entity_type = "📍 Address"
            elif replacement == "[REDACTED AMOUNT]":
                entity_type = "💰 Money"
            elif len(replacement.split()) == 3 and replacement.replace(" ", "").replace(",", "").isalnum():
                entity_type = "📅 Date"
            else:
                entity_type = "❓ Other"
            
            mapping_data.append({
                "Type": entity_type,
                "Original": original,
                "Replaced With": replacement,
                "Length": len(original)
            })
        
        # Create DataFrame
        df = pd.DataFrame(mapping_data)
        
        # Add filters
        col1, col2 = st.columns([1, 3])
        
        with col1:
            # Filter by entity type
            entity_types = ["All"] + sorted(df["Type"].unique().tolist())
            selected_type = st.selectbox("Filter by Type:", entity_types)
            
            if selected_type != "All":
                df = df[df["Type"] == selected_type]
        
        with col2:
            # Search functionality
            search_term = st.text_input("🔍 Search original text:", placeholder="Enter text to search...")
            if search_term:
                df = df[df["Original"].str.contains(search_term, case=False, na=False)]
        
        st.markdown(f"**Showing {len(df)} of {len(mapping_data)} entities**")
        
        # Display table
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Type": st.column_config.TextColumn("Type", width="small"),
                "Original": st.column_config.TextColumn("Original Text", width="medium"),
                "Replaced With": st.column_config.TextColumn("Replacement", width="medium"),
                "Length": st.column_config.NumberColumn("Characters", width="small")
            }
        )
        
        # Summary statistics
        if len(df) > 0:
            st.markdown("---")
            st.markdown("### 📊 Summary Statistics")
            
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Total Entities", len(df))
            
            with col2:
                avg_length = df["Length"].mean()
                st.metric("Avg. Length", f"{avg_length:.1f}")
            
            with col3:
                max_length = df["Length"].max()
                longest = df[df["Length"] == max_length]["Original"].iloc[0]
                st.metric("Longest Text", f"{max_length} chars")
                st.caption(f'"{longest[:30]}..."' if len(longest) > 30 else f'"{longest}"')
            
            with col4:
                # Count by type
                type_counts = df["Type"].value_counts()
                most_common = type_counts.index[0]
                st.metric("Most Common Type", type_counts.iloc[0])
                st.caption(most_common)
        
        # Export options
        st.markdown("---")
        st.markdown("### 💾 Export Options")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # Export as CSV
            csv_data = df.to_csv(index=False)
            st.download_button(
                label="📊 Download as CSV",
                data=csv_data,
                file_name="entity_mapping.csv",
                mime="text/csv"
            )
        
        with col2:
            # Export as JSON
            json_data = df.to_json(orient="records", indent=2)
            st.download_button(
                label="📋 Download as JSON",
                data=json_data,
                file_name="entity_mapping.json",
                mime="application/json"
            )
        
        with col3:
            # Export filtered results as PDF
            if len(df) > 0:
                mapping_dict = dict(zip(df["Original"], df["Replaced With"]))
                mapping_pdf = create_mapping_pdf(mapping_dict)
                st.download_button(
                    label="📄 Download as PDF",
                    data=mapping_pdf.getvalue(),
                    file_name="entity_mapping_filtered.pdf",
                    mime="application/pdf"
                )


def main():
    init_session()
    
    # Main title
    st.title("🔒 Legal Document Pseudonymizer")
    
    # Create tabs
    tab1, tab2, tab3 = st.tabs(["📖 User Guide", "🔒 Document Processor", "📋 Entity Mapping Table"])
    
    with tab1:
        show_user_guide()
    
    with tab2:
        show_document_processor()
    
    with tab3:
        show_entity_mapping_table()


if __name__ == "__main__":
    main()