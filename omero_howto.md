---
layout: default
title: CCI help and documentation page
---

<div id="md-content" />

<script>
const imageRegex = /!\[(?<altText>.*)\]\s*\((?<imageURL>.+)\)|img\s*src="(?<imageURL1>[^"]*)"\s*alt="(?<altText1>[^"]*)" \/>|img\s*alt="(?<altText2>[^"]*)"\s*src="(?<imageURL2>[^"]*)" \/>/gm;

async function fetchMarkdownAndImages(mdUrl) {
  const baseUrl = mdUrl.substring(0, mdUrl.lastIndexOf('/') + 1);
  
  // Fetch markdown content
  const mdResponse = await fetch(mdUrl);
  const mdText = await mdResponse.text();

  // Extract image URLs using regex from search result [3]
  let images = [];
  let match;

  while ((match = imageRegex.exec(mdText)) !== null) {
    const src = match.groups.imageURL || match.groups.imageURL1 || match.groups.imageURL2;
    const absoluteUrl = new URL(src, baseUrl).href;
    images.push(absoluteUrl);
  }

  // Fetch all images in parallel
  const imageResponses = await Promise.all(
    images.map(url => fetch(url).catch(e => null))
  );

  // Create object with markdown and images
  return {
    markdown: mdText,
    baseUrl, 
    images: await Promise.all(imageResponses.map(async (res, i) => ({
      url: images[i],
      status: res ? res.status : 404,
      content: res ? await res.blob() : null
    })))
  };
}

// Usage
fetchMarkdownAndImages('https://raw.githubusercontent.com/CCI-GU-Sweden/Omero_GU/test/main/static/help.md')
  .then(({markdown, baseUrl, images}) => {
    console.log('Fetched images:', images);
    
    // Render markdown with resolved URLs
    const resolvedMarkdown = markdown.replace(imageRegex, (match, ...args) => {
      const groups = args.pop();
      const src = groups.imageURL || groups.imageURL1 || groups.imageURL2;
      const absoluteUrl = new URL(src, baseUrl).href;
      return match.replace(src, absoluteUrl);
    });

    document.getElementById('md-content').innerHTML = `<md>${resolvedMarkdown}</md>`;
    renderMarkdown();
  })
  .catch(console.error);
</script>
<script src='https://cdn.jsdelivr.net/gh/MarketingPipeline/Markdown-Tag/markdown-tag.js'></script>
