
/**
 * Download JSON file to the user's computer
 * 
 * @param name - Name of the file without extension (will be sanitized)
 * @param data - Data to be saved in the file
 */

export function downloadJSONFile(name: string, data: any) {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "text/json",
  });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;

  // Sanitize file name
  let file_name = name.toLowerCase(); // Lowercase
  file_name = file_name.replace(/\s+/g, "_"); // Replace spaces with underscores
  file_name = file_name.replace(/[\\/:"*?<>|]+/g, ""); // Remove invalid characters
  file_name = file_name.replace(/_+/g, "_"); // Remove duplicate underscores

  link.download = `${name}.json`;
  link.click();
  window.URL.revokeObjectURL(url);
}

/**
 * Download multiple JSON files to the user's computer
 * Note: Browser will block multiple downloads unless they are triggered by user interaction
 * 
 * @param files - Array of objects containing name and data for each file
 */
export function downloadJSONFiles(files: { name: string; data: any }[]) {
  files.forEach((file, index) => {
    setTimeout(() => {
      downloadJSONFile(file.name, file.data);
    }, index * 1000);
  });
}