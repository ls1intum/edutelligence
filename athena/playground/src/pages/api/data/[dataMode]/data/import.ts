import type { NextApiRequest, NextApiResponse } from "next";
import fs from "fs";
import path from "path";
import formidable, { IncomingForm } from "formidable";
import unzipper from "unzipper";

export const config = {
  api: {
    bodyParser: false,
  },
};

const UPLOAD_DIR = path.join(process.cwd(), "data/evaluation");

async function handleFileUpload(file: formidable.File, directory: string) {
  if (file.mimetype === "application/zip") {
    await new Promise((resolve, reject) => {
      fs.createReadStream(file.filepath)
        .pipe(unzipper.Parse())
        .on("entry", entry => {
          if (entry.path.startsWith("__MACOSX") || entry.path.endsWith(".DS_Store")) {
            entry.autodrain();
            return;
          }
          const fullPath = path.join(directory, entry.path);
          if (entry.type === "Directory") {
            fs.mkdirSync(fullPath, { recursive: true });
            entry.autodrain();
          } else {
            const dirName = path.dirname(fullPath);
            fs.mkdirSync(dirName, { recursive: true });
            entry.pipe(fs.createWriteStream(fullPath));
          }
        })
        .on("close", resolve)
        .on("error", reject);
    });
  } else if (file.mimetype === "application/json") {
    const filePath = path.join(directory, file.originalFilename || file.newFilename);
    fs.copyFileSync(file.filepath, filePath);
  } else {
    throw new Error("Unsupported file type");
  }
}

async function handler(req: NextApiRequest, res: NextApiResponse) {
  const form = new IncomingForm();
  const dataMode = req.query.dataMode as string;

  const directory = path.join(UPLOAD_DIR, dataMode.slice("evaluation-".length));

  if (!fs.existsSync(directory)) {
    fs.mkdirSync(directory, { recursive: true });
  }

  form.parse(req, async (err, fields, files) => {
    if (err) {
      return res.status(500).json({ error: "Failed to parse form data" });
    }

    try {
      const fileArray = (Array.isArray(files.file) ? files.file : [files.file]).filter((file): file is NonNullable<typeof file> => file !== undefined);

      for (const file of fileArray) {
        await handleFileUpload(file, directory);
      }

      res.status(200).json({ success: true });
    } catch (error) {
      console.error(error);
      res.status(500).json({ error: "Failed to handle file upload" });
    }
  });
}

export default handler;
