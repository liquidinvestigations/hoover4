import { PDFiumNodeExample } from './basic-example.js';
import { readFile, writeFile } from 'fs/promises';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

class PDFTextExtractor extends PDFiumNodeExample {
  constructor() {
    super();
    this.extractedText = [];
    this.textStats = {};
  }

  async extractAllText() {
    if (!this.pdfDocument) {
      throw new Error('No PDF document loaded');
    }

    const pageCount = this.pdfiumInstance.FPDF_GetPageCount(this.pdfDocument);
    console.log(`\nExtracting text from all ${pageCount} pages...`);

    this.extractedText = [];
    let totalCharacters = 0;
    let totalWords = 0;

    for (let pageIndex = 0; pageIndex < pageCount; pageIndex++) {
      console.log(`Processing page ${pageIndex + 1}/${pageCount}...`);

      const pageText = await this.extractPageText(pageIndex);
      this.extractedText.push({
        pageNumber: pageIndex + 1,
        text: pageText,
        characterCount: pageText.length,
        wordCount: this.countWords(pageText),
      });

      totalCharacters += pageText.length;
      totalWords += this.countWords(pageText);
    }

    this.textStats = {
      totalPages: pageCount,
      totalCharacters,
      totalWords,
      averageWordsPerPage: Math.round(totalWords / pageCount),
    };

    console.log('\n=== Text Extraction Complete ===');
    console.log(`Total characters: ${totalCharacters}`);
    console.log(`Total words: ${totalWords}`);
    console.log(`Average words per page: ${this.textStats.averageWordsPerPage}`);

    return this.extractedText;
  }

  async extractPageText(pageIndex) {
    const page = this.pdfiumInstance.FPDF_LoadPage(this.pdfDocument, pageIndex);
    if (!page) {
      throw new Error(`Failed to load page ${pageIndex}`);
    }

    const textPage = this.pdfiumInstance.FPDFText_LoadPage(page);
    if (!textPage) {
      this.pdfiumInstance.FPDF_ClosePage(page);
      throw new Error(`Failed to load text page ${pageIndex}`);
    }

    const charCount = this.pdfiumInstance.FPDFText_CountChars(textPage);
    let extractedText = '';

    // Extract all characters
    for (let i = 0; i < charCount; i++) {
      const unicode = this.pdfiumInstance.FPDFText_GetUnicode(textPage, i);
      if (unicode > 0) {
        // Handle basic Unicode characters
        if (unicode < 0x10000) {
          extractedText += String.fromCharCode(unicode);
        } else {
          // Handle surrogate pairs for characters beyond BMP
          const surrogate1 = 0xd800 + ((unicode - 0x10000) >> 10);
          const surrogate2 = 0xdc00 + ((unicode - 0x10000) & 0x3ff);
          extractedText += String.fromCharCode(surrogate1, surrogate2);
        }
      }
    }

    // Clean up
    this.pdfiumInstance.FPDFText_ClosePage(textPage);
    this.pdfiumInstance.FPDF_ClosePage(page);

    return extractedText;
  }

  countWords(text) {
    return text.split(/\s+/).filter((word) => word.length > 0).length;
  }

  searchText(query, caseSensitive = false) {
    if (!this.extractedText.length) {
      throw new Error('No text extracted yet. Call extractAllText() first.');
    }

    const searchQuery = caseSensitive ? query : query.toLowerCase();
    const results = [];

    for (const pageData of this.extractedText) {
      const searchText = caseSensitive ? pageData.text : pageData.text.toLowerCase();
      const matches = [];
      let index = 0;

      while ((index = searchText.indexOf(searchQuery, index)) !== -1) {
        // Get context around the match
        const contextStart = Math.max(0, index - 50);
        const contextEnd = Math.min(searchText.length, index + searchQuery.length + 50);
        const context = pageData.text.substring(contextStart, contextEnd);

        matches.push({
          position: index,
          context: context.trim(),
          matchedText: pageData.text.substring(index, index + query.length),
        });

        index += searchQuery.length;
      }

      if (matches.length > 0) {
        results.push({
          pageNumber: pageData.pageNumber,
          matchCount: matches.length,
          matches: matches,
        });
      }
    }

    return results;
  }

  generateWordFrequency(minWordLength = 3) {
    if (!this.extractedText.length) {
      throw new Error('No text extracted yet. Call extractAllText() first.');
    }

    const wordCounts = {};
    const stopWords = new Set([
      'the',
      'a',
      'an',
      'and',
      'or',
      'but',
      'in',
      'on',
      'at',
      'to',
      'for',
      'of',
      'with',
      'by',
      'is',
      'are',
      'was',
      'were',
      'be',
      'been',
      'being',
      'have',
      'has',
      'had',
      'do',
      'does',
      'did',
      'will',
      'would',
      'could',
      'should',
      'may',
      'might',
      'must',
      'can',
      'this',
      'that',
      'these',
      'those',
    ]);

    for (const pageData of this.extractedText) {
      const words = pageData.text
        .toLowerCase()
        .replace(/[^\w\s]/g, ' ')
        .split(/\s+/)
        .filter(
          (word) => word.length >= minWordLength && !stopWords.has(word) && !/^\d+$/.test(word), // Exclude pure numbers
        );

      for (const word of words) {
        wordCounts[word] = (wordCounts[word] || 0) + 1;
      }
    }

    // Sort by frequency
    const sortedWords = Object.entries(wordCounts)
      .sort(([, a], [, b]) => b - a)
      .slice(0, 50); // Top 50 words

    return sortedWords;
  }

  async saveTextToFile(outputPath) {
    if (!this.extractedText.length) {
      throw new Error('No text extracted yet. Call extractAllText() first.');
    }

    let content = `PDF Text Extraction Report\n`;
    content += `Generated: ${new Date().toISOString()}\n`;
    content += `===========================================\n\n`;

    content += `Document Statistics:\n`;
    content += `- Total Pages: ${this.textStats.totalPages}\n`;
    content += `- Total Characters: ${this.textStats.totalCharacters}\n`;
    content += `- Total Words: ${this.textStats.totalWords}\n`;
    content += `- Average Words per Page: ${this.textStats.averageWordsPerPage}\n\n`;

    content += `Text by Page:\n`;
    content += `=============\n\n`;

    for (const pageData of this.extractedText) {
      content += `--- Page ${pageData.pageNumber} ---\n`;
      content += `Characters: ${pageData.characterCount} | Words: ${pageData.wordCount}\n\n`;
      content += pageData.text;
      content += `\n\n${'='.repeat(50)}\n\n`;
    }

    await writeFile(outputPath, content, 'utf8');
    console.log(`Text extraction saved to: ${outputPath}`);
  }

  async saveAnalysisReport(outputPath) {
    if (!this.extractedText.length) {
      throw new Error('No text extracted yet. Call extractAllText() first.');
    }

    // Generate word frequency analysis
    const wordFrequency = this.generateWordFrequency();

    let report = `PDF Analysis Report\n`;
    report += `Generated: ${new Date().toISOString()}\n`;
    report += `===========================================\n\n`;

    report += `Document Overview:\n`;
    report += `- Total Pages: ${this.textStats.totalPages}\n`;
    report += `- Total Characters: ${this.textStats.totalCharacters}\n`;
    report += `- Total Words: ${this.textStats.totalWords}\n`;
    report += `- Average Words per Page: ${this.textStats.averageWordsPerPage}\n\n`;

    report += `Page-by-Page Statistics:\n`;
    report += `Page\tWords\tCharacters\n`;
    report += `----\t-----\t----------\n`;
    for (const pageData of this.extractedText) {
      report += `${pageData.pageNumber}\t${pageData.wordCount}\t${pageData.characterCount}\n`;
    }
    report += `\n`;

    report += `Most Frequent Words:\n`;
    report += `Rank\tWord\t\tFrequency\n`;
    report += `----\t----\t\t---------\n`;
    wordFrequency.forEach(([word, count], index) => {
      report += `${index + 1}\t${word.padEnd(12)}\t${count}\n`;
    });

    await writeFile(outputPath, report, 'utf8');
    console.log(`Analysis report saved to: ${outputPath}`);
  }
}

// Example usage
async function runTextExtractionExample() {
  const extractor = new PDFTextExtractor();

  try {
    const pdfPath = process.argv[2] || join(__dirname, 'sample.pdf');

    console.log('PDFium Text Extraction Example');
    console.log('===============================');

    // Initialize and load PDF
    await extractor.initialize();

    try {
      await extractor.loadPDF(pdfPath);
    } catch (error) {
      console.error('\nError: Could not load PDF file.');
      console.log('Please provide a valid PDF file path as an argument:');
      console.log('node text-extraction-example.js /path/to/your/file.pdf');
      console.log('\nOr place a file named "sample.pdf" in the examples/node/ directory.');
      return;
    }

    // Extract all text
    await extractor.extractAllText();

    // Save extracted text
    const textOutputPath = join(__dirname, 'extracted-text.txt');
    await extractor.saveTextToFile(textOutputPath);

    // Save analysis report
    const reportOutputPath = join(__dirname, 'analysis-report.txt');
    await extractor.saveAnalysisReport(reportOutputPath);

    // Search for specific terms (example)
    const searchTerms = ['PDF', 'document', 'page'];
    for (const term of searchTerms) {
      console.log(`\n=== Search Results for "${term}" ===`);
      const results = extractor.searchText(term, false);
      if (results.length > 0) {
        let totalMatches = 0;
        for (const result of results) {
          console.log(`Page ${result.pageNumber}: ${result.matchCount} matches`);
          totalMatches += result.matchCount;

          // Show first match context
          if (result.matches.length > 0) {
            console.log(`  Context: "${result.matches[0].context}"`);
          }
        }
        console.log(`Total matches: ${totalMatches}`);
      } else {
        console.log('No matches found');
      }
    }

    console.log('\n=== Text Extraction Example completed successfully! ===');
  } catch (error) {
    console.error('Text extraction example failed:', error.message);
    console.error(error.stack);
  } finally {
    extractor.cleanup();
  }
}

// Run the example if this file is executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runTextExtractionExample().catch(console.error);
}

export { PDFTextExtractor };
