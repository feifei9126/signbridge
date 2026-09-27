const video = document.querySelector("#demo-video");
const chapters = [...document.querySelectorAll(".chapter")];

if (video && chapters.length) {
  for (const chapter of chapters) {
    chapter.addEventListener("click", () => {
      video.currentTime = Number(chapter.dataset.time);
      video.scrollIntoView({ behavior: "smooth", block: "center" });
      video.play().catch(() => {
        // Autoplay may be blocked; native controls remain available.
      });
    });
  }

  video.addEventListener("timeupdate", () => {
    const currentIndex = chapters.findLastIndex(
      (chapter) => video.currentTime >= Number(chapter.dataset.time),
    );
    chapters.forEach((chapter, index) => {
      chapter.classList.toggle("is-active", index === currentIndex);
    });
  });
}
