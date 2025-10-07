"""
Legal Document Pseudonymization Tool
====================================

This tool pseudonymizes sensitive entities in legal documents while preserving
document structure and relationships (e.g., date intervals).

For new developers:
1. Each entity type has its own Extractor and Pseudonymizer class
2. To add new entity types: inherit from the abstract base classes
3. The PseudonymizationPipeline orchestrates everything
4. All configuration is in PseudonymConfig

Architecture:
- EntityExtractor (ABC) -> DateExtractor, OrganizationExtractor, etc.
- EntityPseudonymizer (ABC) -> DatePseudonymizer, OrganizationPseudonymizer, etc.
- PseudonymizationPipeline -> coordinates all extractors and pseudonymizers
"""

import spacy
import random
import datetime
import re
import logging
import hashlib
from typing import List
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from abc import ABC, abstractmethod

# ============================================================================
# SHARED UTILITIES
# ============================================================================

class NumberRandomizer:
    """Shared logic for randomizing numerical values"""
    @staticmethod
    def randomize_number(value: float, preserve_small: bool = True) -> float:
        if preserve_small and 0 < value <= 10:
            return random.choice([x for x in range(1, 11) if x != int(value)])
        else:
            multiplier = random.uniform(0.85, 1.15)
            return value * multiplier


# ============================================================================
# DATA STRUCTURES
# ============================================================================

@dataclass
class Entity:
    """Represents an extracted entity from text"""
    start: int
    end: int
    label: str
    text: str
    confidence: Optional[float] = None


@dataclass
class PseudonymConfig:
    """Configuration for pseudonymization settings"""
    model_name: str = "en_core_web_trf"
    
    date_range_start: datetime.date = datetime.date(2000, 1, 1)
    date_range_end: datetime.date = datetime.date(2025, 12, 31)
    
    enable_date_extraction: bool = True
    enable_organization_extraction: bool = True
    enable_money_extraction: bool = True
    enable_number_extraction: bool = True          
    enable_address_extraction: bool = True
    enable_legal_person_extraction: bool = True
    enable_spacy_extraction: bool = True
    
    def __post_init__(self):
        self.target_labels = {"PERSON", "ORG", "GPE", "MONEY", "NUMBER", "ADDRESS", "DATE", "FAC", "LEGAL_PERSON"}


# ============================================================================
# ABSTRACT BASE CLASSES
# ============================================================================

class EntityExtractor(ABC):
    """Base class for all entity extractors"""
    
    @abstractmethod
    def extract(self, text: str) -> List[Entity]:
        """Extract entities of this type from text"""
        pass
    
    @property
    @abstractmethod
    def entity_types(self) -> List[str]:
        """Return list of entity type labels this extractor handles"""
        pass
    
    def _overlaps_existing(self, start: int, end: int, entities: List[Entity]) -> bool:
        """Check if span overlaps with existing entities"""
        return any(start < e.end and end > e.start for e in entities)


class EntityPseudonymizer(ABC):
    """Base class for all entity pseudonymizers"""
    
    def __init__(self):
        self.replacement_cache: Dict[str, str] = {}
    
    @abstractmethod
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        """Generate pseudonymized version of entity"""
        pass
    
    def prepare(self, all_entities: List[Entity]) -> None:
        """Optional: Prepare pseudonymizer with all entities from document"""
        pass
    
    def get_replacement(self, original_text: str, entity_label: str) -> str:
        """Get cached replacement or create new one"""
        if original_text not in self.replacement_cache:
            self.replacement_cache[original_text] = self.pseudonymize(original_text, entity_label)
        return self.replacement_cache[original_text]


# ============================================================================
# DATE HANDLING
# ============================================================================

class DateExtractor(EntityExtractor):
    """Extracts dates with context awareness"""
    
    def __init__(self):
        self.date_patterns = {
            'no_later_than': re.compile(
                r"\bno\s+later\s+than\s+(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b", 
                re.IGNORECASE
            ),
            'day_month_year': re.compile(
                r"\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b",
                re.IGNORECASE
            ),
            'month_day_year': re.compile(
                r"\b((?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4})\b",
                re.IGNORECASE
            ),
            'abbreviated_months': re.compile(
                r"\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})\b",
                re.IGNORECASE
            )
        }
    
    @property
    def entity_types(self) -> List[str]:
        return ["DATE"]
    
    def extract(self, text: str) -> List[Entity]:
        entities = []
        
        for pattern_name, pattern in self.date_patterns.items():
            for match in pattern.finditer(text):
                date_text = match.group(1).strip()
                start_pos = match.start(1)
                end_pos = match.end(1)
                
                if not self._overlaps_existing(start_pos, end_pos, entities):
                    entities.append(Entity(
                        start=start_pos,
                        end=end_pos,
                        label="DATE",
                        text=date_text
                    ))
        
        return sorted(entities, key=lambda x: x.start)


class DatePseudonymizer(EntityPseudonymizer):
    """Pseudonymizes dates while preserving relative intervals"""
    
    def __init__(self):
        super().__init__()
        self.date_mapping: Dict[datetime.date, datetime.date] = {}
        
        self.date_formats = [
            '%d %B %Y', '%B %d %Y', '%B %d, %Y', '%d %b %Y',
            '%b %d %Y', '%b %d, %Y', '%Y-%m-%d', '%d/%m/%Y',
            '%m/%d/%Y', '%d-%m-%Y', '%m-%d-%Y'
        ]
    
    def prepare(self, all_entities: List[Entity]) -> None:
        date_entities = [e for e in all_entities if e.label == "DATE"]
        if not date_entities:
            self.date_mapping = {}
            return
        
        parsed_dates = []
        for entity in date_entities:
            parsed_date = self._parse_date(entity.text)
            if parsed_date:
                parsed_dates.append(parsed_date)
        
        if not parsed_dates:
            self.date_mapping = {}
            return
        
        unique_dates = sorted(list(set(parsed_dates)))
        
        if len(unique_dates) == 1:
            self._create_single_date_mapping(unique_dates[0])
        else:
            self._create_interval_preserving_mapping(unique_dates)
    
    def _create_single_date_mapping(self, original_date: datetime.date) -> None:
        random_days = random.randint(-7300, 7300)
        base_date = datetime.date(2010, 1, 1)
        new_date = base_date + datetime.timedelta(days=random_days)
        self.date_mapping = {original_date: new_date}
    
    def _create_interval_preserving_mapping(self, unique_dates: List[datetime.date]) -> None:
        earliest_date = unique_dates[0]
        
        random_days = random.randint(-7300, 7300)
        base_date = datetime.date(2010, 1, 1)
        new_start_date = base_date + datetime.timedelta(days=random_days)
        
        self.date_mapping = {}
        for original_date in unique_dates:
            days_from_start = (original_date - earliest_date).days
            new_date = new_start_date + datetime.timedelta(days=days_from_start)
            self.date_mapping[original_date] = new_date
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        parsed_date = self._parse_date(original_text.strip())
        
        if parsed_date and parsed_date in self.date_mapping:
            shifted_date = self.date_mapping[parsed_date]
            return self._format_date_like_original(shifted_date, original_text)
        else:
            return f"[UNPARSEABLE DATE: {original_text}]"
    
    def _parse_date(self, date_str: str) -> Optional[datetime.date]:
        for date_format in self.date_formats:
            try:
                return datetime.datetime.strptime(date_str, date_format).date()
            except ValueError:
                continue
        return None
    
    def _format_date_like_original(self, date_obj: datetime.date, original_str: str) -> str:
        if any(month in original_str for month in ['January', 'February', 'March', 'April', 'May', 'June', 
                                                   'July', 'August', 'September', 'October', 'November', 'December']):
            return date_obj.strftime('%d %B %Y')
        elif any(month in original_str for month in ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                                                     'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']):
            return date_obj.strftime('%d %b %Y')
        elif '-' in original_str:
            if original_str.startswith('20') or original_str.startswith('19'):
                return date_obj.strftime('%Y-%m-%d')
            else:
                return date_obj.strftime('%d-%m-%Y')
        elif '/' in original_str:
            return date_obj.strftime('%d/%m/%Y')
        else:
            return date_obj.strftime('%d %B %Y')


# ============================================================================
# ORGANIZATION HANDLING
# ============================================================================

class OrganizationExtractor(EntityExtractor):
    """Extracts organization names using comprehensive regex patterns"""
    
    def __init__(self):
        self.corporate_suffixes = [
            "Pte Ltd", "Pvt Ltd", "Private Limited", "Ltd", "Limited",
            "LLP", "LLC", "PLLC", "LP", "L.P.", "L.L.C.", "L.L.P.",
            "Inc","Incorporated", "Corp", "Corporation", 
            "Co", "Company", "Holdings", "Group", "PLC", "plc",
            "AG", "GmbH", "S.A.", "SAS", "SARL", "B.V.", "N.V.",
            "Pty Ltd", "Pty Limited"
        ]
        
        long_suffixes = [s for s in self.corporate_suffixes if len(s) > 2]
        short_suffixes = [s for s in self.corporate_suffixes if len(s) <= 2]
        
        long_suffix_pattern = "|".join([re.escape(suffix) for suffix in long_suffixes])
        short_suffix_pattern = "|".join([rf"\b{re.escape(suffix)}\b" for suffix in short_suffixes])
        
        if long_suffixes and short_suffixes:
            suffix_pattern = f"(?:{long_suffix_pattern}|{short_suffix_pattern})"
        elif long_suffixes:
            suffix_pattern = long_suffix_pattern
        else:
            suffix_pattern = short_suffix_pattern
        
        self.company_patterns = [
            re.compile(rf"\b([A-Z]{{2,4}}\s+Bank\s+(?:{suffix_pattern})(?:,\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+Branch)?)", re.IGNORECASE),
            re.compile(rf"(?<!of\s)\b([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){{0,2}}\s+(?:{suffix_pattern}))", re.IGNORECASE),
        ]
        
        self.exclusion_words = {
            "payable", "transfer", "wire", "to", "by", "from", 
            "agreed", "sell", "having", "incorporated", "and", "with", "signed",
            "the", "this", "that", "said", "such", "other", "any", "all", "of"
        }

    @property
    def entity_types(self) -> List[str]:
        return ["ORG"]

    def extract(self, text: str) -> List[Entity]:
        entities = []
        
        for pattern in self.company_patterns:
            for match in pattern.finditer(text):
                company_name = match.group(1).strip() if match.lastindex and match.lastindex >= 1 else match.group(0).strip()
                
                if (len(company_name) > 5
                    and not self._contains_exclusion_words(company_name)
                    and not self._overlaps_existing(match.start(), match.end(), entities)
                    and self._is_valid_company_name(company_name)):
                    
                    entities.append(Entity(
                        start=match.start(),
                        end=match.end(),
                        label="ORG",
                        text=company_name
                    ))
        
        return sorted(entities, key=lambda x: x.start)

    def _contains_exclusion_words(self, text: str) -> bool:
        text_lower = text.lower()
        words = text_lower.split()
        
        for word in words[:-2]:
            if word in self.exclusion_words:
                return True
        return False
    
    def _is_valid_company_name(self, text: str) -> bool:
        words = text.split()
        if len(words) < 2:
            return False
        
        name_part = " ".join(words[:-1]) if len(words) > 1 else words[0]
        
        if not re.search(r'[A-Za-z]{2,}', name_part):
            return False
            
        first_word = words[0].lower()
        if first_word in ["a", "an", "the", "such", "said", "other", "of"]:
            return False
        
        return True


class OrganizationPseudonymizer(EntityPseudonymizer):
    """Replace organizations while preserving their corporate suffix"""
    
    def __init__(self):
        super().__init__()
        self.counter = 0
        
        self.corporate_suffixes = [
            "Pte Ltd", "Pvt Ltd", "Private Limited", "Ltd", "Limited",
            "LLP", "LLC", "PLLC", "LP", "L.P.", "L.L.C.", "L.L.P.",
            "Inc", "Incorporated", "Corp", "Corporation", 
            "Co", "Company", "Holdings", "Group", "PLC", "plc",
            "AG", "GmbH", "S.A.", "SAS", "SARL", "B.V.", "N.V.",
            "Pty Ltd", "Pty Limited"
        ]

    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        self.counter += 1
        letter = chr(ord("A") + (self.counter - 1) % 26)
        
        branch_match = re.search(r',\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+Branch', original_text, re.IGNORECASE)
        suffix = self._extract_corporate_suffix(original_text)
        
        if branch_match and suffix:
            return f"Bank {letter} {suffix}, Location {letter} Branch"
        elif suffix:
            return f"ORG {letter} {suffix}"
        else:
            return f"ORG {letter}"
    
    def _extract_corporate_suffix(self, text: str) -> str:
        text_without_branch = re.sub(r',\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\s+Branch.*$', '', text, flags=re.IGNORECASE)
        text_clean = re.sub(r'[.,;:]+\s*$', '', text_without_branch.strip())
        
        sorted_suffixes = sorted(self.corporate_suffixes, key=len, reverse=True)
        
        for suffix in sorted_suffixes:
            if text_clean.lower().endswith(suffix.lower()):
                start_pos = len(text_clean) - len(suffix)
                return text_clean[start_pos:]
        
        return ""


# ============================================================================
# MONEY HANDLING
# ============================================================================

class MoneyExtractor(EntityExtractor):
    """Extracts money amounts in multiple currencies"""
    
    def __init__(self):
        self.money_patterns = [
            re.compile(r"(USD|EUR|GBP|CAD|AUD|SGD|HKD|JPY|CNY|CHF|SEK|NOK|DKK)\s+[\d,]+(?:,\d{3})*(?:\.\d{2})?\s+\([^)]*(?:dollars?|euros?|pounds?|yen|yuan|francs?|krona|krone)[^)]*\)", re.IGNORECASE),
            re.compile(r"(USD|EUR|GBP|CAD|AUD|SGD|HKD|JPY|CNY|CHF|SEK|NOK|DKK)\s+[\d,]+(?:,\d{3})*(?:\.\d{2})?", re.IGNORECASE),
            re.compile(r"[\$€£¥₹₩₪₽¢]\s*[\d,]+(?:,\d{3})*(?:\.\d{2})?"),
            re.compile(r"[\d,]+(?:,\d{3})*(?:\.\d{2})?\s+(?:dollars?|euros?|pounds?|yen|yuan|francs?|krona|krone)", re.IGNORECASE)
        ]
    
    @property
    def entity_types(self) -> List[str]:
        return ["MONEY"]
    
    def extract(self, text: str) -> List[Entity]:
        entities = []
        
        for pattern in self.money_patterns:
            for match in pattern.finditer(text):
                if not self._overlaps_existing(match.start(), match.end(), entities):
                    entities.append(Entity(
                        start=match.start(),
                        end=match.end(),
                        label="MONEY",
                        text=match.group(0)
                    ))
        
        return sorted(entities, key=lambda x: x.start)


class MoneyPseudonymizer(EntityPseudonymizer):
    """Replace money amounts with randomized amounts"""
    
    def __init__(self):
        super().__init__()
        
        self.currency_symbols = {
            'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥', 'CNY': '¥',
            'CAD': 'C$', 'AUD': 'A$', 'SGD': 'S$', 'HKD': 'HK$',
            'CHF': 'CHF', 'SEK': 'kr', 'NOK': 'kr', 'DKK': 'kr'
        }
        
        self.currency_words = {
            'USD': 'Dollars', 'EUR': 'Euros', 'GBP': 'Pounds', 'JPY': 'Yen', 
            'CNY': 'Yuan', 'CAD': 'Canadian Dollars', 'AUD': 'Australian Dollars',
            'SGD': 'Singapore Dollars', 'HKD': 'Hong Kong Dollars',
            'CHF': 'Swiss Francs', 'SEK': 'Swedish Krona', 'NOK': 'Norwegian Krone', 'DKK': 'Danish Krone'
        }

    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        result = self._handle_full_format(original_text)
        if result: return result
        
        result = self._handle_currency_code_format(original_text)
        if result: return result
        
        result = self._handle_symbol_format(original_text)
        if result: return result
        
        result = self._handle_written_format(original_text)
        if result: return result
        
        return "[REDACTED AMOUNT]"
    
    def _handle_full_format(self, text: str) -> str:
        pattern = r"(USD|EUR|GBP|CAD|AUD|SGD|HKD|JPY|CNY|CHF|SEK|NOK|DKK)\s+([\d,]+(?:\.\d{2})?)\s+\(([^)]*)\)"
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            currency = match.group(1).upper()
            amount_str = match.group(2).replace(',', '')
            original_amount = float(amount_str)
            
            new_amount = NumberRandomizer.randomize_number(original_amount, preserve_small=False)
            new_amount_int = int(round(new_amount))
            formatted_amount = f"{new_amount_int:,}"
            
            written_amount = self._number_to_written(new_amount_int)
            currency_word = self.currency_words.get(currency, "Units")
            
            return f"{currency} {formatted_amount} ({written_amount} {currency_word})"
        
        return None
    
    def _handle_currency_code_format(self, text: str) -> str:
        pattern = r"(USD|EUR|GBP|CAD|AUD|SGD|HKD|JPY|CNY|CHF|SEK|NOK|DKK)\s+([\d,]+(?:\.\d{2})?)"
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            currency = match.group(1).upper()
            amount_str = match.group(2).replace(',', '')
            original_amount = float(amount_str)
            
            new_amount = NumberRandomizer.randomize_number(original_amount, preserve_small=False)
            
            if '.' in amount_str:
                formatted_amount = f"{new_amount:,.2f}"
            else:
                formatted_amount = f"{int(round(new_amount)):,}"
            
            return f"{currency} {formatted_amount}"
        
        return None
    
    def _handle_symbol_format(self, text: str) -> str:
        pattern = r"([\$€£¥₹₩₪₽¢])\s*([\d,]+(?:\.\d{2})?)"
        match = re.search(pattern, text)
        
        if match:
            symbol = match.group(1)
            amount_str = match.group(2).replace(',', '')
            original_amount = float(amount_str)
            
            new_amount = NumberRandomizer.randomize_number(original_amount, preserve_small=False)
            
            if '.' in amount_str:
                formatted_amount = f"{new_amount:,.2f}"
            else:
                formatted_amount = f"{int(round(new_amount)):,}"
            
            return f"{symbol}{formatted_amount}"
        
        return None
    
    def _handle_written_format(self, text: str) -> str:
        pattern = r"([\d,]+(?:\.\d{2})?)\s+(dollars?|euros?|pounds?|yen|yuan|francs?|krona|krone)"
        match = re.search(pattern, text, re.IGNORECASE)
        
        if match:
            amount_str = match.group(1).replace(',', '')
            currency_word = match.group(2).lower()
            original_amount = float(amount_str)
            
            new_amount = NumberRandomizer.randomize_number(original_amount, preserve_small=False)
            
            if '.' in amount_str:
                formatted_amount = f"{new_amount:,.2f}"
            else:
                formatted_amount = f"{int(round(new_amount)):,}"
            
            return f"{formatted_amount} {currency_word}"
        
        return None
    
    def _number_to_written(self, amount: int) -> str:
        if amount == 0:
            return "Zero"
        
        if amount >= 1_000_000_000:
            billions = amount // 1_000_000_000
            remainder = amount % 1_000_000_000
            result = f"{self._convert_hundreds(billions)} Billion"
            if remainder >= 1_000_000:
                millions = remainder // 1_000_000
                result += f" {self._convert_hundreds(millions)} Million"
            return result
        elif amount >= 1_000_000:
            millions = amount // 1_000_000
            remainder = amount % 1_000_000
            result = f"{self._convert_hundreds(millions)} Million"
            if remainder >= 1_000:
                thousands = remainder // 1_000
                result += f" {self._convert_hundreds(thousands)} Thousand"
            return result
        elif amount >= 1_000:
            thousands = amount // 1_000
            remainder = amount % 1_000
            result = f"{self._convert_hundreds(thousands)} Thousand"
            if remainder > 0:
                result += f" {self._convert_hundreds(remainder)}"
            return result
        else:
            return self._convert_hundreds(amount)
    
    def _convert_hundreds(self, num: int) -> str:
        if num == 0:
            return ""
        
        ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
                "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
                "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        
        if num < 20:
            return ones[num]
        elif num < 100:
            return tens[num // 10] + ("-" + ones[num % 10] if num % 10 != 0 else "")
        else:
            result = ones[num // 100] + " Hundred"
            remainder = num % 100
            if remainder > 0:
                result += " " + self._convert_hundreds(remainder)
            return result


# ============================================================================
# NUMBER HANDLING
# ============================================================================

class NumberExtractor(EntityExtractor):
    """Extracts standalone numbers, percentages, and quantities"""
    
    def __init__(self):
        self.number_patterns = [
            re.compile(r"\b\d+(?:\.\d+)?%", re.IGNORECASE),
            re.compile(r"\b\d{1,3}(?:,\d{3})+(?!\s*(?:AD|BC|CE|BCE))\b"),
            re.compile(r"(?<!\d\.)\b\d+\.\d+(?![\.\d])\b"),
            re.compile(r"\b\d+(?:\.\d+)?\s+(?:people|persons?|shares?|units?|times?|fold|percent|percentage|items?|pieces?|copies?)\b", re.IGNORECASE),
            re.compile(r"(?<![\d\-\.])\b(?!(?:19|20)\d{2}\b)(?!\d{1,4}\s+(?:Street|Road|Avenue|Drive|Lane|Boulevard|St|Rd|Ave|Dr|Ln|Blvd))\d{2,6}(?![\d\-\.])\b"),
            re.compile(r"\b\d+:\d+\b"),
            re.compile(r"\b\d+/\d+\b")
        ]
        
        self.exclusion_patterns = [
            re.compile(r"\b(?:19|20)\d{2}(?:\s*[-–]\s*(?:19|20)\d{2})?\b"),
            re.compile(r"\b\d{1,2}[\.\/\-]\d{1,2}[\.\/\-](?:\d{2}|\d{4})\b"),
            re.compile(r"[\+\(]?\d{1,4}[\)\s\-]?\d{3,4}[\s\-]?\d{3,4}"),
            re.compile(r"\b\d{5,6}\b|\b[A-Z]{1,2}\d{1,2}[A-Z]?\s?\d[A-Z]{2}\b"),
            re.compile(r"(?:case|ref|no|number)[\.\s]*\d+", re.IGNORECASE)
        ]

    @property
    def entity_types(self) -> List[str]:
        return ["NUMBER"]

    def extract(self, text: str) -> List[Entity]:
        entities = []
        
        for pattern in self.number_patterns:
            for match in pattern.finditer(text):
                number_text = match.group(0).strip()
                start_pos = match.start()
                end_pos = match.end()
                
                if (not self._should_exclude(text, start_pos, end_pos)
                    and not self._overlaps_existing(start_pos, end_pos, entities)
                    and self._is_valid_number(number_text)):
                    
                    entities.append(Entity(
                        start=start_pos,
                        end=end_pos,
                        label="NUMBER",
                        text=number_text
                    ))
        
        return sorted(entities, key=lambda x: x.start)

    def _should_exclude(self, text: str, start: int, end: int) -> bool:
        context_start = max(0, start - 20)
        context_end = min(len(text), end + 20)
        context = text[context_start:context_end]
        
        for pattern in self.exclusion_patterns:
            if pattern.search(context):
                return True
        
        return False

    def _is_valid_number(self, text: str) -> bool:
        if re.search(r'\b(?:years?|months?|weeks?|days?|hours?|minutes?|seconds?)\b', text, re.IGNORECASE):
            return False
        
        if not re.search(r'\d', text):
            return False
        
        number_match = re.search(r'\d+', text)
        if number_match:
            number_value = int(number_match.group(0))
            if number_value > 1_000_000:
                return False
        
        return True


class NumberPseudonymizer(EntityPseudonymizer):
    """Randomize numbers while preserving format and context"""
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        text = original_text.strip()
        
        if text.endswith('%'):
            return self._handle_percentage(text)
        
        if ':' in text:
            return self._handle_ratio(text)
        
        if '/' in text:
            return self._handle_fraction(text)
        
        unit_match = re.search(r'(\d+(?:\.\d+)?)\s+(\w+)', text)
        if unit_match:
            return self._handle_number_with_unit(unit_match.group(1), unit_match.group(2))
        
        if ',' in text:
            return self._handle_comma_number(text)
        
        if '.' in text:
            return self._handle_decimal(text)
        
        return self._handle_integer(text)

    def _handle_percentage(self, text: str) -> str:
        number_str = text[:-1]
        try:
            original_value = float(number_str)
            new_value = NumberRandomizer.randomize_number(original_value, preserve_small=False)
            
            if '.' in number_str:
                decimal_places = len(number_str.split('.')[1])
                return f"{new_value:.{decimal_places}f}%"
            else:
                return f"{int(round(new_value))}%"
        except ValueError:
            return text

    def _handle_ratio(self, text: str) -> str:
        parts = text.split(':')
        if len(parts) == 2:
            try:
                left = float(parts[0])
                right = float(parts[1])
                new_left = NumberRandomizer.randomize_number(left, preserve_small=True)
                new_right = NumberRandomizer.randomize_number(right, preserve_small=True)
                return f"{int(round(new_left))}:{int(round(new_right))}"
            except ValueError:
                pass
        return text

    def _handle_fraction(self, text: str) -> str:
        parts = text.split('/')
        if len(parts) == 2:
            try:
                numerator = float(parts[0])
                denominator = float(parts[1])
                new_num = NumberRandomizer.randomize_number(numerator, preserve_small=True)
                new_den = NumberRandomizer.randomize_number(denominator, preserve_small=True)
                return f"{int(round(new_num))}/{int(round(new_den))}"
            except ValueError:
                pass
        return text

    def _handle_number_with_unit(self, number_str: str, unit: str) -> str:
        try:
            original_value = float(number_str)
            new_value = NumberRandomizer.randomize_number(original_value, preserve_small=False)
            
            if unit.lower() in ['years', 'months', 'weeks', 'hours']:
                return f"{new_value:.1f} {unit}"
            else:
                return f"{int(round(new_value))} {unit}"
        except ValueError:
            return f"{number_str} {unit}"

    def _handle_comma_number(self, text: str) -> str:
        try:
            number_value = float(text.replace(',', ''))
            new_value = NumberRandomizer.randomize_number(number_value, preserve_small=False)
            return f"{int(round(new_value)):,}"
        except ValueError:
            return text

    def _handle_decimal(self, text: str) -> str:
        try:
            original_value = float(text)
            new_value = NumberRandomizer.randomize_number(original_value, preserve_small=False)
            
            decimal_places = len(text.split('.')[1])
            return f"{new_value:.{decimal_places}f}"
        except ValueError:
            return text

    def _handle_integer(self, text: str) -> str:
        try:
            original_value = int(text)
            new_value = NumberRandomizer.randomize_number(float(original_value), preserve_small=True)
            return str(int(round(new_value)))
        except ValueError:
            return text


# ============================================================================
# ADDRESS HANDLING
# ============================================================================

class AddressExtractor(EntityExtractor):
    """Extracts address patterns including Singapore-specific formats"""
    
    def __init__(self):
        self.address_patterns = [
            re.compile(r"\b\d+\s+[A-Z][a-z]+\s+(?:Street|Road|Avenue|Drive|Lane|Boulevard|Quay),\s*Singapore\s+\d{6}\b"),
            re.compile(r"\b(?:One|Two|Three|Four|Five|\d+)\s+[A-Z][a-z]*\s+(?:Quay|Plaza|Square|Tower|Building|Centre|Center)(?:,\s*Level\s*\d+)?(?:,\s*\d+\s+[A-Z][a-z]*\s+(?:Street|Road|Quay))?(?:,\s*Singapore\s+\d{6})?\b"),
            re.compile(r"\b\d+\s+[A-Z][a-z]+\s+(?:Street|Road|Avenue|Drive|Lane|Boulevard),\s*[A-Z][a-z]+,\s*[A-Z]{2}\s+\d{5}\b"),
            re.compile(r"\b\d+\s+[A-Z][a-z]+\s+(?:Street|St|Road|Rd|Avenue|Ave|Drive|Dr|Lane|Ln|Boulevard|Blvd|Walk|Close|Crescent|Place|Park|Gardens|Heights|View|Terrace|Rise|Hill|Grove|Way|Circuit|Centre|Center|Quay)\b"),
            re.compile(r"\b(?:One|Two|Three|Four|Five|Six|Seven|Eight|Nine|Ten)\s+[A-Z][a-z]*\s+(?:Street|Road|Avenue|Quay|Boulevard|Plaza|Square|Tower|Building|Centre|Center)\b")
        ]
    
    @property
    def entity_types(self) -> List[str]:
        return ["ADDRESS"]
    
    def extract(self, text: str) -> List[Entity]:
        entities = []
        
        for pattern in self.address_patterns:
            for match in pattern.finditer(text):
                if not self._overlaps_existing(match.start(), match.end(), entities):
                    entities.append(Entity(
                        start=match.start(),
                        end=match.end(),
                        label="ADDRESS",
                        text=match.group(0)
                    ))
        
        return sorted(entities, key=lambda x: x.start)


class AddressPseudonymizer(EntityPseudonymizer):
    """Replace addresses with consistent hash-based codes"""
    
    def __init__(self, salt: str = "legal_doc_addresses_2024"):
        super().__init__()
        self.salt = salt
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        normalized_address = self._normalize_address(original_text)
        
        hash_input = f"{self.salt}:{normalized_address}".encode('utf-8')
        hash_object = hashlib.sha256(hash_input)
        hash_hex = hash_object.hexdigest()
        
        hex_substring = hash_hex[:6]
        address_code = str(int(hex_substring, 16) % 1000000).zfill(6)
        
        return f"[ADDRESS {address_code}]"
    
    def _normalize_address(self, address: str) -> str:
        normalized = re.sub(r'\s+', ' ', address.lower().strip())
        
        replacements = {
            ' st ': ' street ',
            ' rd ': ' road ',
            ' ave ': ' avenue ',
            ' dr ': ' drive ',
            ' ln ': ' lane ',
            ' blvd ': ' boulevard ',
            'centre': 'center',
            ',': '',
            '.': ''
        }
        
        for old, new in replacements.items():
            normalized = normalized.replace(old, new)
        
        return normalized.strip()


# ============================================================================
# LEGAL ROLE-AWARE PERSON HANDLING
# ============================================================================

@dataclass
class PersonEntity(Entity):
    """Extended entity class for persons with legal roles"""
    role: Optional[str] = None
    title: Optional[str] = None
    organization: Optional[str] = None


class LegalPersonExtractor(EntityExtractor):
    """Extracts persons with explicit legal roles"""
    
    def __init__(self):
        self.legal_roles = {
            'plaintiff', 'defendant', 'complainant', 'respondent', 'petitioner', 
            'appellant', 'appellee', 'cross-defendant', 'third-party defendant',
            'intervenor', 'amicus', 'witness', 'expert witness',
            'grantor', 'grantee', 'licensor', 'licensee', 'buyer', 'seller',
            'vendor', 'purchaser', 'contractor', 'subcontractor', 'guarantor',
            'borrower', 'lender', 'mortgagor', 'mortgagee', 'lessor', 'lessee',
            'trustee', 'beneficiary', 'settlor', 'executor', 'administrator',
            'ceo', 'cfo', 'coo', 'president', 'chairman', 'director', 'officer',
            'manager', 'partner', 'shareholder', 'stockholder', 'member',
            'managing director', 'general counsel', 'secretary', 'treasurer',
            'attorney', 'lawyer', 'counsel', 'advocate', 'barrister', 'solicitor',
            'judge', 'magistrate', 'arbitrator', 'mediator', 'paralegal',
            'legal assistant', 'court reporter', 'clerk',
            'guardian', 'conservator', 'agent', 'representative', 'proxy',
            'assignor', 'assignee', 'successor', 'heir', 'beneficiary'
        }
        
        self.professional_titles = {
            'mr', 'mrs', 'ms', 'miss', 'dr', 'prof', 'professor', 'hon',
            'honorable', 'justice', 'chief justice', 'associate justice'
        }
        
        self.role_priority = {
            'plaintiff': 100, 'defendant': 100,
            'appellant': 95, 'respondent': 95, 'petitioner': 95,
            'witness': 80, 'expert witness': 85,
            'attorney': 70, 'lawyer': 70, 'counsel': 70,
            'director': 50, 'ceo': 50, 'president': 50,
            'partner': 60, 'manager': 45,
        }
        
        sorted_roles = sorted(self.legal_roles, key=len, reverse=True)
        sorted_titles = sorted(self.professional_titles, key=len, reverse=True)
        
        roles_pattern = '|'.join(re.escape(role) for role in sorted_roles)
        titles_pattern = '|'.join(re.escape(title) for title in sorted_titles)
        
        self.role_patterns = [
            re.compile(r'(?:between\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}),\s+([A-Za-z\s]+)\s+of\s+([A-Z][A-Za-z\s&]+?)\s+Ltd\s*\("?([^)"]+)"?\)', re.IGNORECASE),
            re.compile(r'(?:,|and)\s+([A-Z][a-z]+\s+[A-Z][a-z]+)\s*\(["""]([^)"""]+)["""]\)', re.IGNORECASE),
            re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*\(\s*([^)]+)\s*\)', re.IGNORECASE),
            re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2}),\s+([A-Za-z\s]{2,30})(?=\s*\(|,|\.|$)', re.IGNORECASE),
            re.compile(r'\b(' + roles_pattern + r')\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)(?=\s+[a-z(]|\s*[.,(;:]|\s*$)', re.IGNORECASE),
            re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s+the\s+([a-zA-Z\s]+?)(?:,|\.|$)', re.IGNORECASE),
            re.compile(r'\b(' + titles_pattern + r')\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', re.IGNORECASE),
            re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s+as\s+([a-zA-Z\s]+?)(?:,|\.|$|\s+of)', re.IGNORECASE),
            re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\s*\(\s*([^,)]{2,30}),\s*([^)]{2,50})\s*\)', re.IGNORECASE)
        ]
    
    @property
    def entity_types(self) -> List[str]:
        return ["LEGAL_PERSON"]
    
    def extract(self, text: str) -> List[Entity]:
        text = text.replace('"', '"').replace('"', '"')
        text = text.replace('""', '"')
        text = text.replace("''", "'")
        entities = []
        seen_names = {}
        
        for i, pattern in enumerate(self.role_patterns):
            for match in pattern.finditer(text):
                person_entity = self._process_role_match(match, i)
                
                if person_entity and self._is_valid_person_entity(person_entity):
                    if not self._overlaps_existing(person_entity.start, person_entity.end, entities):
                        entities.append(person_entity)
                        
                        bare_name = self._extract_name_from_entity_text(person_entity.text)
                        if bare_name and person_entity.role:
                            seen_names[bare_name.lower()] = person_entity.role
        
        for name, role in seen_names.items():
            name_words = name.split()
            
            if len(name_words) >= 2:
                pattern_str = r'\b' + r'\s+'.join(re.escape(word) for word in name_words) + r'\b'
                name_pattern = re.compile(pattern_str, re.IGNORECASE)
                
                for match in name_pattern.finditer(text):
                    if not self._overlaps_existing(match.start(), match.end(), entities):
                        entities.append(PersonEntity(
                            start=match.start(),
                            end=match.end(),
                            label="LEGAL_PERSON",
                            text=match.group(0),
                            role=role
                        ))
            elif len(name_words) == 1:
                name_pattern = re.compile(r'\b' + re.escape(name) + r'\b', re.IGNORECASE)
                for match in name_pattern.finditer(text):
                    if not self._overlaps_existing(match.start(), match.end(), entities):
                        entities.append(PersonEntity(
                            start=match.start(),
                            end=match.end(),
                            label="LEGAL_PERSON",
                            text=match.group(0),
                            role=role
                        ))
        
        return sorted(entities, key=lambda x: x.start)
    
    def _process_role_match(self, match: re.Match, pattern_index: int) -> Optional[PersonEntity]:
        groups = match.groups()
        
        if pattern_index == 0 and len(groups) == 4:
            name = groups[0].strip()
            title = groups[1].strip()
            organization = groups[2].strip()
            role = groups[3].strip()
            
            clean_text = f'{name}, {title} of {organization} Ltd ("{role}")'
            
            actual_start = match.start()
            if match.group(0).lower().startswith('between'):
                actual_start = match.start() + len('between ')
            
            return PersonEntity(
                start=actual_start,
                end=match.end(),
                label="LEGAL_PERSON",
                text=clean_text,
                role=self._normalize_role(role),
                title=title,
                organization=organization
            )
        
        elif pattern_index == 1 and len(groups) == 2:
            name = groups[0].strip()
            role = groups[1].strip()
            
            actual_start = match.start()
            if match.group(0).startswith('and '):
                actual_start += 4
            elif match.group(0).startswith(', '):
                actual_start += 2
            
            return PersonEntity(
                start=actual_start,
                end=match.end(),
                label="LEGAL_PERSON",
                text=name + ' ("' + role + '")',
                role=self._normalize_role(role)
            )
        
        elif len(groups) == 2:
            name_candidate = groups[0].strip()
            role_candidate = groups[1].strip()
            
            if ' and ' in role_candidate or ',' in role_candidate:
                roles = re.split(r'\s+and\s+|,\s*', role_candidate)
                roles = [r.strip() for r in roles if self._looks_like_role(r)]
                
                if roles:
                    primary_role = max(roles, key=lambda r: self._get_role_priority(r))
                    role_candidate = primary_role
            
            if self._looks_like_name(name_candidate) and self._looks_like_role(role_candidate):
                name, role = name_candidate, role_candidate
            elif self._looks_like_role(name_candidate) and self._looks_like_name(role_candidate):
                role, name = name_candidate, role_candidate
            else:
                return None
            
            return PersonEntity(
                start=match.start(),
                end=match.end(),
                label="LEGAL_PERSON",
                text=match.group(0),
                role=self._normalize_role(role)
            )
        
        elif len(groups) == 3:
            name = groups[0].strip()
            role = groups[1].strip()
            organization = groups[2].strip()
            
            return PersonEntity(
                start=match.start(),
                end=match.end(),
                label="LEGAL_PERSON",
                text=match.group(0),
                role=self._normalize_role(role),
                organization=organization
            )
        
        return None
    
    def _extract_name_from_entity_text(self, entity_text: str) -> Optional[str]:
        match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*?)(?:,|\s+\()', entity_text)
        if match:
            return match.group(1).strip()
        
        match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', entity_text)
        if match:
            return match.group(1).strip()
        
        role_name_match = re.search(r'\b(?:plaintiff|defendant|attorney|dr\.?|mr\.?|mrs\.?|ms\.?)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)', entity_text, re.IGNORECASE)
        if role_name_match:
            return role_name_match.group(1).strip()
        
        return None
    
    def _get_role_priority(self, role: str) -> int:
        role_clean = role.lower().strip()
        return self.role_priority.get(role_clean, 0)
    
    def _looks_like_name(self, text: str) -> bool:
        words = text.split()
        if len(words) < 1 or len(words) > 4:
            return False
        
        company_indicators = ['ltd', 'llc', 'llp', 'inc', 'corp', 'company', 'holdings', 'bank']
        text_lower = text.lower()
        if any(indicator in text_lower for indicator in company_indicators):
            return False
        
        return all(word[0].isupper() and word[1:].islower() for word in words if word.isalpha())
    
    def _looks_like_role(self, text: str) -> bool:
        text_lower = text.lower().strip()
        text_clean = re.sub(r'^(the\s+|a\s+|an\s+)', '', text_lower)
        text_clean = re.sub(r'\s+(thereof|therein)$', '', text_clean)
        
        return (text_clean in self.legal_roles or 
                text_clean in self.professional_titles or
                any(role in text_clean for role in self.legal_roles))
    
    def _normalize_role(self, role: str) -> str:
        role_lower = role.lower().strip()
        role_clean = re.sub(r'^(the\s+|a\s+|an\s+)', '', role_lower)
        
        role_mappings = {
            'atty': 'attorney',
            'mgr': 'manager',
            'mgmt': 'management',
            'chmn': 'chairman',
            'chrmn': 'chairman',
            'pres': 'president',
            'v.p.': 'vice president',
            'vp': 'vice president'
        }
        
        return role_mappings.get(role_clean, role_clean)
    
    def _is_valid_person_entity(self, entity: PersonEntity) -> bool:
        if len(entity.text) < 3 or len(entity.text) > 150:
            return False
        
        main_text = entity.text.split('(')[0].strip()
        company_indicators = ['inc', 'corp', 'llc', 'llp', 'company', 'co.']
        main_text_lower = main_text.lower()
        
        if any(indicator in main_text_lower for indicator in company_indicators):
            return False
        
        non_person_starts = [
            'the plaintiff initiated', 'the defendant filed', 'the settlement',
            'the hearing', 'the trial', 'the case', 'the matter', 'the suit',
            'the dispute', 'the claim', 'the lawsuit', 'the action', 'the proceeding',
        ]
        
        if any(main_text_lower.startswith(pattern) for pattern in non_person_starts):
            return False
        
        words = main_text.split()
        if len(words) > 3:
            name_like_words = [w for w in words if w[0].isupper() and w[1:].islower() and w.isalpha()]
            if len(name_like_words) < 1:
                return False
        
        return True


class LegalPersonPseudonymizer(EntityPseudonymizer):
    """Pseudonymize persons based on their legal roles"""
    
    def __init__(self, use_hash_consistency: bool = True):
        super().__init__()
        self.use_hash_consistency = use_hash_consistency
        self.role_counters = {}
        self.hash_salt = "legal_persons_2024"
        self.name_to_role_registry = {}
        self.processed_entities = []
    
    def prepare(self, all_entities: List[Entity]) -> None:
        legal_persons = [e for e in all_entities if e.label == "LEGAL_PERSON"]
        bare_persons = [e for e in all_entities if e.label == "PERSON"]
        
        self.name_to_role_registry = {}
        
        for entity in legal_persons:
            if isinstance(entity, PersonEntity) and entity.role:
                name = self._extract_bare_name(entity.text)
                if name:
                    name_lower = name.lower()
                    self.name_to_role_registry[name_lower] = entity.role
                    
                    replacement = self._generate_hash_based_pseudonym(name, entity.role)
                    
                    self.replacement_cache[name] = replacement
                    self.replacement_cache[entity.text] = replacement
        
        for entity in bare_persons:
            matched_role = self._find_matching_role(entity.text)
            if matched_role:
                replacement = self._generate_hash_based_pseudonym(entity.text, matched_role)
                self.replacement_cache[entity.text] = replacement
    
    def _extract_bare_name(self, entity_text: str) -> Optional[str]:
        match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*?)(?:,|\s+\()', entity_text)
        if match:
            return match.group(1).strip()
        
        match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', entity_text)
        if match:
            return match.group(1).strip()
        
        match = re.match(r'^(?:Attorney|Counsel|Dr|Mr|Mrs|Ms)\.?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)', entity_text, re.IGNORECASE)
        if match:
            return match.group(1).strip()
        
        if re.match(r'^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+$', entity_text):
            return entity_text.strip()
        
        return None
    
    def _find_matching_role(self, bare_name: str) -> Optional[str]:
        bare_name_lower = bare_name.lower().strip()
        
        if bare_name_lower in self.name_to_role_registry:
            return self.name_to_role_registry[bare_name_lower]
        
        for known_name, role in self.name_to_role_registry.items():
            if (self._names_likely_same_person(bare_name_lower, known_name) or
                self._names_likely_same_person(known_name, bare_name_lower)):
                return role
        
        return None
    
    def _names_likely_same_person(self, name1: str, name2: str) -> bool:
        name1_parts = name1.split()
        name2_parts = name2.split()
        
        if name1 == name2:
            return True
        
        if (len(name1_parts) >= 2 and len(name2_parts) >= 2 and
            name1_parts[0] == name2_parts[0] and
            name1_parts[-1] == name2_parts[-1]):
            return True
        
        if (len(name1_parts) >= 2 and len(name2_parts) >= 2):
            shorter = name1_parts if len(name1_parts) <= len(name2_parts) else name2_parts
            longer = name2_parts if len(name1_parts) <= len(name2_parts) else name1_parts
            
            if all(part in longer for part in shorter):
                return True
        
        return False
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        person_info = self._parse_person_info(original_text)
        
        if person_info['role']:
            return self._generate_role_based_pseudonym(person_info)
        else:
            return self._generate_generic_pseudonym()
    
    def get_replacement(self, original_text: str, entity_label: str) -> str:
        if original_text not in self.replacement_cache:
            if hasattr(self, '_current_entity') and isinstance(self._current_entity, PersonEntity):
                replacement = self._generate_role_based_pseudonym_from_entity(self._current_entity)
            else:
                matched_role = self._find_matching_role(original_text.strip())
                if matched_role:
                    bare_name = self._extract_bare_name(original_text) or original_text
                    replacement = self._generate_role_based_pseudonym({'name': bare_name, 'role': matched_role})
                else:
                    replacement = self.pseudonymize(original_text, entity_label)
            self.replacement_cache[original_text] = replacement
        return self.replacement_cache[original_text]
    
    def _parse_person_info(self, text: str) -> Dict[str, Optional[str]]:
        patterns = [
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*\(\s*([^)]+)\s*\)',
            r'([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*),\s+([^,]+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return {'name': match.group(1), 'role': match.group(2).strip()}
        
        return {'name': None, 'role': None}
    
    def _generate_role_based_pseudonym_from_entity(self, entity: PersonEntity) -> str:
        role = entity.role if entity.role else "person"
        
        if self.use_hash_consistency:
            bare_name = self._extract_bare_name(entity.text)
            if not bare_name:
                bare_name = entity.text
            return self._generate_hash_based_pseudonym(bare_name, role)
        else:
            return self._generate_counter_based_pseudonym(role)
    
    def _generate_role_based_pseudonym(self, person_info: Dict[str, Optional[str]]) -> str:
        role = person_info.get('role', 'person') or 'person'
        
        if self.use_hash_consistency:
            name_for_hash = person_info.get('name', '') or 'unknown'
            return self._generate_hash_based_pseudonym(name_for_hash, role)
        else:
            return self._generate_counter_based_pseudonym(role)
    
    def _generate_hash_based_pseudonym(self, name: str, role: str) -> str:
        role_normalized = self._normalize_role_for_pseudonym(role)
        name_normalized = name.lower().strip()
        
        hash_input = f"{self.hash_salt}:{name_normalized}:{role_normalized}".encode('utf-8')
        hash_object = hashlib.sha256(hash_input)
        hash_hex = hash_object.hexdigest()
        
        letter_index = int(hash_hex[:2], 16) % 26
        letter = chr(ord('A') + letter_index)
        
        return f"{role_normalized} {letter}"
    
    def _generate_counter_based_pseudonym(self, role: str) -> str:
        role_normalized = self._normalize_role_for_pseudonym(role)
        
        if role_normalized not in self.role_counters:
            self.role_counters[role_normalized] = 0
        
        self.role_counters[role_normalized] += 1
        letter = chr(ord('A') + (self.role_counters[role_normalized] - 1) % 26)
        
        return f"{role_normalized} {letter}"
    
    def _normalize_role_for_pseudonym(self, role: str) -> str:
        role_clean = role.lower().strip()
        
        role_mappings = {
            'plaintiff': 'Plaintiff',
            'defendant': 'Defendant', 
            'attorney': 'Attorney',
            'lawyer': 'Counsel',
            'counsel': 'Counsel',
            'partner': 'Partner',
            'ceo': 'CEO',
            'president': 'President',
            'director': 'Director',
            'judge': 'Judge',
            'witness': 'Witness',
            'buyer': 'Buyer',
            'seller': 'Seller',
            'grantor': 'Grantor',
            'grantee': 'Grantee',
            'trustee': 'Trustee'
        }
        
        return role_mappings.get(role_clean, 'Person')
    
    def _generate_generic_pseudonym(self) -> str:
        return self._generate_counter_based_pseudonym('person')

    def _reconstruct_structured_entity(self, original_text: str, base_pseudonym: str, all_replacements: dict) -> str:
        pattern1 = r'^(.+?),\s+(.+?)\s+of\s+(.+?)\s+\("(.+?)"\)$'
        match = re.match(pattern1, original_text, re.IGNORECASE)
        
        if match:
            title = match.group(2).strip()
            organization = match.group(3).strip()
            role = match.group(4).strip()
            
            org_pseudo = all_replacements.get(organization, organization)
            
            return f'{base_pseudonym}, {title} of {org_pseudo} ("{role}")'
        
        pattern2 = r'^(.+?)\s+\("(.+?)"\)$'
        match = re.match(pattern2, original_text, re.IGNORECASE)
        
        if match:
            role = match.group(2).strip()
            return f'{base_pseudonym} ("{role}")'
        
        return base_pseudonym

    def get_replacement_with_structure(self, original_text: str, entity_label: str, all_replacements: dict = None) -> str:
        if original_text not in self.replacement_cache:
            if hasattr(self, '_current_entity') and isinstance(self._current_entity, PersonEntity):
                base_pseudonym = self._generate_role_based_pseudonym_from_entity(self._current_entity)
            else:
                matched_role = self._find_matching_role(original_text.strip())
                if matched_role:
                    bare_name = self._extract_bare_name(original_text) or original_text
                    base_pseudonym = self._generate_role_based_pseudonym({'name': bare_name, 'role': matched_role})
                else:
                    base_pseudonym = self.pseudonymize(original_text, entity_label)
            
            if all_replacements:
                final_pseudonym = self._reconstruct_structured_entity(original_text, base_pseudonym, all_replacements)
            else:
                final_pseudonym = base_pseudonym
            
            self.replacement_cache[original_text] = final_pseudonym
        
        return self.replacement_cache[original_text]


# ============================================================================
# SPACY-BASED EXTRACTION
# ============================================================================

class SpacyExtractor(EntityExtractor):
    """Uses spaCy NER for general entity types"""
    
    def __init__(self, nlp_model, target_labels: set):
        self.nlp = nlp_model
        self.target_labels = target_labels
        self.exclusion_words = {
            "payable", "transfer", "wire", "agreed", "sell", "having", "incorporated"
        }
    
    @property
    def entity_types(self) -> List[str]:
        return list(self.target_labels)
    
    def extract(self, text: str) -> List[Entity]:
        entities = []
        doc = self.nlp(text)
        
        for ent in doc.ents:
            if (ent.label_ in self.target_labels 
                and len(ent.text.strip()) >= 2 
                and not self._contains_exclusion_words(ent.text)
                and self._is_valid_entity(ent)):
                
                entities.append(Entity(
                    start=ent.start_char,
                    end=ent.end_char,
                    label=ent.label_,
                    text=ent.text
                ))
        
        return sorted(entities, key=lambda x: x.start)
    
    def _contains_exclusion_words(self, text: str) -> bool:
        text_lower = text.lower()
        return any(word in text_lower for word in self.exclusion_words)
    
    def _is_valid_entity(self, ent) -> bool:
        if ent.label_ == "PERSON":
            context_window = 50
            start_context = max(0, ent.start_char - context_window)
            end_context = min(len(ent.doc.text), ent.end_char + context_window)
            context = ent.doc.text[start_context:end_context].lower()
            
            legal_indicators = ['(', 'plaintiff', 'defendant', 'counsel', 'attorney', 'partner', 'judge', 'witness', 'dr.', 'hon.']
            if any(indicator in context for indicator in legal_indicators):
                return False
        
        if ent.label_ == "ORG":
            text_lower = ent.text.lower()
            if any(word in text_lower for word in ['bank', 'branch']) and 'ltd' in text_lower:
                return False
        
        if ent.label_ == "DATE":
            if re.search(r"\b(?:no\s+later\s+than|before|after|during|within)\b", ent.text, re.IGNORECASE):
                return False
            if not re.search(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|\d{1,2})\b", ent.text, re.IGNORECASE):
                return False
        
        return True


# ============================================================================
# GENERIC COUNTER-BASED PSEUDONYMIZERS
# ============================================================================

class CounterBasedPseudonymizer(EntityPseudonymizer):
    """Generic pseudonymizer that uses counters"""
    
    def __init__(self, prefix: str, use_hash: bool = True):
        super().__init__()
        self.prefix = prefix
        self.counter = 0
        self.use_hash = use_hash
        self.salt = f"{prefix.lower()}_pseudonyms_2024"
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        if self.use_hash:
            hash_input = f"{self.salt}:{original_text}".encode('utf-8')
            hash_object = hashlib.sha256(hash_input)
            letter_index = int(hash_object.hexdigest()[:2], 16) % 26
            letter = chr(ord("A") + letter_index)
        else:
            self.counter += 1
            letter = chr(ord("A") + (self.counter - 1) % 26)
        
        return f"{self.prefix} {letter}"


class GPEPseudonymizer(EntityPseudonymizer):
    """Handles geographic/political entities with subcategories"""
    
    def __init__(self, use_hash: bool = True):
        super().__init__()
        self.countries = self._load_countries()
        self.states = self._load_states()
        self.counters = {"COUNTRY": 0, "STATE": 0, "CITY": 0}
        self.use_hash = use_hash
        self.salt = "gpe_pseudonyms_2024"
    
    def _load_countries(self) -> set:
        return {
            "Singapore", "Malaysia", "Thailand", "Indonesia", "Philippines", 
            "Vietnam", "Myanmar", "Cambodia", "Laos", "Brunei",
            "China", "Japan", "South Korea", "Taiwan", "Hong Kong", "Macau",
            "India", "Pakistan", "Bangladesh", "Sri Lanka", "Nepal",
            "United States", "USA", "US", "United Kingdom", "UK", "Canada",
            "Australia", "New Zealand", "Germany", "France", "Italy", "Spain"
        }
    
    def _load_states(self) -> set:
        return {
            "Delaware", "California", "New York", "Texas", "Florida",
            "Johor", "Selangor", "Penang", "Sabah", "Sarawak",
            "Jakarta", "West Java", "Bangkok", "Ontario", "Quebec"
        }
    
    def pseudonymize(self, original_text: str, entity_label: str) -> str:
        text = original_text.strip()
        
        if text in self.countries:
            category = "COUNTRY"
            prefix = "Country"
        elif text in self.states:
            category = "STATE"
            prefix = "State"
        else:
            category = "CITY"
            prefix = "City"
        
        if self.use_hash:
            hash_input = f"{self.salt}:{category}:{text}".encode('utf-8')
            hash_object = hashlib.sha256(hash_input)
            letter_index = int(hash_object.hexdigest()[:2], 16) % 26
            letter = chr(ord("A") + letter_index)
        else:
            self.counters[category] += 1
            letter = chr(ord("A") + (self.counters[category] - 1) % 26)
        
        return f"{prefix} {letter}"


# ============================================================================
# MAIN PIPELINE
# ============================================================================

class PseudonymizationPipeline:
    """Main pipeline that coordinates all extractors and pseudonymizers"""
    
    def __init__(self, config: Optional[PseudonymConfig] = None):
        self.config = config or PseudonymConfig()
        self.nlp = self._load_spacy_model()
        
        self.extractors = self._initialize_extractors()
        self.pseudonymizers = self._initialize_pseudonymizers()
    
    def _load_spacy_model(self):
        models_to_try = [self.config.model_name, "en_core_web_md", "en_core_web_sm"]
        
        for model in models_to_try:
            try:
                return spacy.load(model)
            except OSError:
                logging.warning(f"Could not load spaCy model: {model}")
                continue
        
        raise RuntimeError("No spaCy model found. Please install: python -m spacy download en_core_web_sm")
    
    def _initialize_extractors(self) -> List[EntityExtractor]:
        extractors = []
        
        if self.config.enable_legal_person_extraction:
            extractors.append(LegalPersonExtractor())
        
        if self.config.enable_date_extraction:
            extractors.append(DateExtractor())
        
        if self.config.enable_organization_extraction:
            extractors.append(OrganizationExtractor())
        
        if self.config.enable_money_extraction:
            extractors.append(MoneyExtractor())

        if self.config.enable_number_extraction:
            extractors.append(NumberExtractor())
        
        if self.config.enable_address_extraction:
            extractors.append(AddressExtractor())
        
        if self.config.enable_spacy_extraction:
            extractors.append(SpacyExtractor(self.nlp, {"PERSON", "GPE", "FAC", "ORG"}))
        
        return extractors
    
    def _initialize_pseudonymizers(self) -> Dict[str, EntityPseudonymizer]:
        return {
            "DATE": DatePseudonymizer(),
            "ORG": OrganizationPseudonymizer(),
            "MONEY": MoneyPseudonymizer(),
            "NUMBER": NumberPseudonymizer(),
            "ADDRESS": AddressPseudonymizer(),
            "LEGAL_PERSON": LegalPersonPseudonymizer(use_hash_consistency=True),
            "PERSON": CounterBasedPseudonymizer("Person", use_hash=True),
            "GPE": GPEPseudonymizer(use_hash=True),
            "FAC": CounterBasedPseudonymizer("Building", use_hash=True)
        }
    
    def pseudonymize(self, text: str) -> Tuple[str, Dict[str, str]]:
        if not text or not text.strip():
            return text, {}
        
        all_entities = self._extract_all_entities(text)
        all_entities = self._remove_overlaps(all_entities)
        self._prepare_pseudonymizers(all_entities)
        
        return self._apply_pseudonymization(text, all_entities)
    
    def _extract_all_entities(self, text: str) -> List[Entity]:
        all_entities = []
        
        for extractor in self.extractors:
            try:
                entities = extractor.extract(text)
                all_entities.extend(entities)
                logging.debug(f"{extractor.__class__.__name__} found {len(entities)} entities")
            except Exception as e:
                logging.error(f"Error in {extractor.__class__.__name__}: {e}")
        
        return all_entities
    
    def _remove_overlaps(self, entities: List[Entity]) -> List[Entity]:
        if not entities:
            return entities

        priority_order = {
            "LEGAL_PERSON": 1,
            "PERSON": 2, 
            "ORG": 3, 
            "GPE": 4, 
            "FAC": 5, 
            "ADDRESS": 6, 
            "MONEY": 7, 
            "NUMBER": 8, 
            "DATE": 9
        }
        
        sorted_entities = sorted(entities, key=lambda e: e.start)
        result = []
        
        for entity in sorted_entities:
            overlaps = False
            for i, accepted in enumerate(result):
                if entity.start < accepted.end and entity.end > accepted.start:
                    entity_priority = priority_order.get(entity.label, 10)
                    accepted_priority = priority_order.get(accepted.label, 10)
                    
                    if entity_priority < accepted_priority:
                        result[i] = entity
                    elif entity_priority == accepted_priority and len(entity.text) > len(accepted.text):
                        result[i] = entity
                    
                    overlaps = True
                    break
            
            if not overlaps:
                result.append(entity)
        
        return result
    
    def _prepare_pseudonymizers(self, all_entities: List[Entity]) -> None:
        for label, pseudonymizer in self.pseudonymizers.items():
            relevant_entities = [e for e in all_entities if e.label == label]
            if relevant_entities:
                pseudonymizer.prepare(relevant_entities)
    
    def _apply_pseudonymization(self, text: str, entities: List[Entity]) -> Tuple[str, Dict[str, str]]:
        replacement_mapping = {}
        result_text = text
        
        temp_mapping = {}
        for entity in entities:
            if entity.label in self.pseudonymizers:
                pseudonymizer = self.pseudonymizers[entity.label]
                
                if isinstance(entity, PersonEntity):
                    pseudonymizer._current_entity = entity
                
                if entity.label == "LEGAL_PERSON":
                    if isinstance(entity, PersonEntity) and entity.role:
                        bare_name = self._extract_bare_name_from_entity(entity)
                        base_pseudo = pseudonymizer._generate_hash_based_pseudonym(bare_name, entity.role)
                        temp_mapping[entity.text] = base_pseudo
                    else:
                        temp_mapping[entity.text] = pseudonymizer.pseudonymize(entity.text, entity.label)
                else:
                    temp_mapping[entity.text] = pseudonymizer.get_replacement(entity.text, entity.label)
        
        for entity in entities:
            if entity.label in self.pseudonymizers:
                pseudonymizer = self.pseudonymizers[entity.label]
                
                if entity.label == "LEGAL_PERSON":
                    base_pseudo = temp_mapping.get(entity.text, entity.text)
                    final_pseudo = pseudonymizer._reconstruct_structured_entity(
                        entity.text, 
                        base_pseudo, 
                        temp_mapping
                    )
                    replacement_mapping[entity.text] = final_pseudo
                else:
                    replacement_mapping[entity.text] = temp_mapping[entity.text]
        
        sorted_items = sorted(replacement_mapping.items(), key=lambda x: len(x[0]), reverse=True)
        
        for original, replacement in sorted_items:
            result_text = result_text.replace(original, replacement)
        
        return result_text, replacement_mapping

    def _extract_bare_name_from_entity(self, entity: Entity) -> str:
        match = re.match(r'^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*?)(?:,|\s+\()', entity.text)
        if match:
            return match.group(1).strip()
        return entity.text


# ============================================================================
# PUBLIC API
# ============================================================================

def pseudonymize_text(text: str, config: Optional[PseudonymConfig] = None) -> Tuple[str, Dict[str, str]]:
    """Simple function interface for pseudonymization
    
    Args:
        text: Text to pseudonymize
        config: Optional configuration
        
    Returns:
        Tuple of (pseudonymized_text, replacement_mapping)
    """
    pipeline = PseudonymizationPipeline(config)
    return pipeline.pseudonymize(text)


def create_custom_config(
    enable_date: bool = True,
    enable_organizations: bool = True,
    enable_money: bool = True,
    enable_numbers: bool = True,
    enable_addresses: bool = True,
    enable_legal_persons: bool = True,
    enable_spacy: bool = True,
    spacy_model: str = "en_core_web_sm"
) -> PseudonymConfig:
    """Helper function to create custom configuration"""
    config = PseudonymConfig(model_name=spacy_model)
    config.enable_date_extraction = enable_date
    config.enable_organization_extraction = enable_organizations
    config.enable_money_extraction = enable_money
    config.enable_number_extraction = enable_numbers
    config.enable_address_extraction = enable_addresses
    config.enable_legal_person_extraction = enable_legal_persons
    config.enable_spacy_extraction = enable_spacy
    return config
            