const fs = require("fs");
const path = require("path");
const {
  AlignmentType,
  BorderStyle,
  Document,
  Footer,
  Header,
  HeadingLevel,
  LevelFormat,
  PageNumber,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} = require("docx");

const inputPath = process.argv[2];
const outputPath = process.argv[3];
if (!inputPath || !outputPath) {
  throw new Error("Usage: node markdown_to_docx.js <input.md> <output.docx>");
}

const markdown = fs.readFileSync(inputPath, "utf8").replace(/\r\n/g, "\n");
const lines = markdown.split("\n");
const title = (lines.find((line) => line.startsWith("# ")) || "# Summary")
  .slice(2)
  .trim();

const CONTENT_WIDTH = 9026;
const FONT = "Microsoft YaHei";

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const tableBorders = {
  top: border,
  bottom: border,
  left: border,
  right: border,
  insideHorizontal: border,
  insideVertical: border,
};

function inlineRuns(text, options = {}) {
  const runs = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let cursor = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > cursor) {
      runs.push(new TextRun({ text: text.slice(cursor, match.index), ...options }));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      runs.push(
        new TextRun({
          text: token.slice(2, -2),
          bold: true,
          ...options,
        })
      );
    } else {
      runs.push(
        new TextRun({
          text: token.slice(1, -1),
          font: "Consolas",
          ...options,
        })
      );
    }
    cursor = match.index + token.length;
  }
  if (cursor < text.length) {
    runs.push(new TextRun({ text: text.slice(cursor), ...options }));
  }
  return runs.length ? runs : [new TextRun({ text: "", ...options })];
}

function parseTable(start) {
  const rows = [];
  let index = start;
  while (index < lines.length && lines[index].trim().startsWith("|")) {
    const text = lines[index].trim();
    const cells = text
      .slice(1, -1)
      .split("|")
      .map((cell) => cell.trim());
    if (!cells.every((cell) => /^:?-{3,}:?$/.test(cell))) {
      rows.push(cells);
    }
    index += 1;
  }

  if (!rows.length) {
    return { table: null, nextIndex: start };
  }

  const columns = Math.max(...rows.map((row) => row.length));
  const isVenueTable =
    columns === 2 && rows[0] && rows[0][0].trim().toLowerCase() === "venue";
  const firstWidth =
    columns === 2
      ? isVenueTable
        ? 7000
        : 1760
      : Math.floor(CONTENT_WIDTH / columns);
  const remaining = CONTENT_WIDTH - firstWidth;
  const widths = Array.from({ length: columns }, (_, column) => {
    if (column === 0) return firstWidth;
    return Math.floor(remaining / (columns - 1));
  });
  widths[widths.length - 1] += CONTENT_WIDTH - widths.reduce((a, b) => a + b, 0);

  const table = new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: widths,
    borders: tableBorders,
    rows: rows.map(
      (row, rowIndex) =>
        new TableRow({
          children: Array.from({ length: columns }, (_, column) => {
            const text = row[column] || "";
            return new TableCell({
              width: { size: widths[column], type: WidthType.DXA },
              margins: { top: 80, bottom: 80, left: 120, right: 120 },
              shading:
                rowIndex === 0
                  ? { fill: "DCE6F1", type: ShadingType.CLEAR }
                  : undefined,
              children: [
                new Paragraph({
                  children: inlineRuns(text, {
                    bold: rowIndex === 0,
                  }),
                }),
              ],
            });
          }),
        })
    ),
  });
  return { table, nextIndex: index };
}

function headingParagraph(text, level, options = {}) {
  const levels = {
    1: HeadingLevel.HEADING_1,
    2: HeadingLevel.HEADING_2,
    3: HeadingLevel.HEADING_3,
  };
  return new Paragraph({
    heading: levels[level],
    pageBreakBefore: level === 1,
    keepNext: true,
    alignment: level === 1 ? AlignmentType.CENTER : AlignmentType.LEFT,
    children: inlineRuns(text),
    ...options,
  });
}

const children = [];
for (let index = 0; index < lines.length; ) {
  const line = lines[index];
  if (!line.trim()) {
    index += 1;
    continue;
  }
  if (line.trim().startsWith("|")) {
    const parsed = parseTable(index);
    if (parsed.table) {
      children.push(parsed.table);
      children.push(new Paragraph({ spacing: { after: 80 } }));
      index = parsed.nextIndex;
      continue;
    }
  }
  if (line.startsWith("### ")) {
    children.push(headingParagraph(line.slice(4).trim(), 3));
  } else if (line.startsWith("## ")) {
    children.push(headingParagraph(line.slice(3).trim(), 2));
  } else if (line.startsWith("# ")) {
    children.push(headingParagraph(line.slice(2).trim(), 1));
  } else if (line.startsWith("- ")) {
    const text = line.slice(2).trim();
    const runs = text.startsWith("摘要总结：")
      ? [
          new TextRun({ text: "摘要总结：", bold: true }),
          ...inlineRuns(text.slice("摘要总结：".length)),
        ]
      : inlineRuns(text);
    children.push(
      new Paragraph({
        numbering: { reference: "summary-bullets", level: 0 },
        children: runs,
      })
    );
  } else {
    children.push(new Paragraph({ children: inlineRuns(line.trim()) }));
  }
  index += 1;
}

const doc = new Document({
  creator: "Codex",
  title,
  styles: {
    default: {
      document: {
        run: { font: FONT, size: 21, color: "1F1F1F" },
        paragraph: {
          spacing: { line: 330, after: 100 },
        },
      },
    },
    paragraphStyles: [
      {
        id: "Heading1",
        name: "Heading 1",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { size: 34, bold: true, font: FONT, color: "17365D" },
        paragraph: {
          spacing: { before: 120, after: 260 },
          outlineLevel: 0,
        },
      },
      {
        id: "Heading2",
        name: "Heading 2",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { size: 27, bold: true, font: FONT, color: "2F5597" },
        paragraph: {
          spacing: { before: 260, after: 140 },
          outlineLevel: 1,
        },
      },
      {
        id: "Heading3",
        name: "Heading 3",
        basedOn: "Normal",
        next: "Normal",
        quickFormat: true,
        run: { size: 22, bold: true, font: FONT, color: "1F4E79" },
        paragraph: {
          spacing: { before: 180, after: 80 },
          outlineLevel: 2,
        },
      },
    ],
  },
  numbering: {
    config: [
      {
        reference: "summary-bullets",
        levels: [
          {
            level: 0,
            format: LevelFormat.BULLET,
            text: "•",
            alignment: AlignmentType.LEFT,
            style: {
              paragraph: {
                indent: { left: 720, hanging: 360 },
              },
            },
          },
        ],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 11906, height: 16838 },
          margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
        },
      },
      headers: {
        default: new Header({
          children: [
            new Paragraph({
              alignment: AlignmentType.RIGHT,
              children: [
                new TextRun({
                  text: title,
                  size: 18,
                  color: "666666",
                }),
              ],
            }),
          ],
        }),
      },
      footers: {
        default: new Footer({
          children: [
            new Paragraph({
              alignment: AlignmentType.CENTER,
              children: [
                new TextRun({ text: "第 ", size: 18 }),
                new TextRun({ children: [PageNumber.CURRENT], size: 18 }),
                new TextRun({ text: " 页", size: 18 }),
              ],
            }),
          ],
        }),
      },
      children,
    },
  ],
});

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(outputPath, buffer);
  console.log(outputPath);
});
