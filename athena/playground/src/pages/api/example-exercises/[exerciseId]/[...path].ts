import {NextApiRequest, NextApiResponse} from 'next';
import {promises as fs} from 'fs';
import {join} from 'path';
import Archiver from 'archiver';

const handler = async (req: NextApiRequest, res: NextApiResponse) => {
  const { exerciseId, path } = req.query as { exerciseId: string, path: string[] };
  // example for path: ['submissions', '1.zip'] or just ['solution.zip']

  // remove ".zip" from the last path element
  const filename = path[path.length - 1].replace('.zip', '');
  path[path.length - 1] = filename;

  // Get the folder path
  const folderPath = join(process.cwd(), 'examples', 'exercise-' + exerciseId, ...path);

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
