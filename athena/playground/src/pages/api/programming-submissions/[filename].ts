import {NextApiRequest, NextApiResponse} from 'next';
import {promises as fs} from 'fs';
import {join} from 'path';
import Archiver from 'archiver';

const handler = async (req: NextApiRequest, res: NextApiResponse) => {
  const { filename } = req.query as { filename: string };

  // Set the folder path based on the filename without the .zip extension
  const folderName = filename.replace('.zip', '');
  const folderPath = join(process.cwd(), 'submissions', folderName);

  // Check if the folder exists
  await fs.access(folderPath);

  res.setHeader('Content-Type', 'application/zip');
  res.setHeader('Content-Disposition', `attachment; filename=${filename}`);

  // Create zip archive
  const archive = Archiver('zip', {
    zlib: { level: 9 },
  });

  // Pipe the archive data to the response
  archive.pipe(res);

  // Append the folder to the archive
  archive.directory(folderPath, false);

  // Finalize the archive and send the response
  await archive.finalize();
};

export default handler;
