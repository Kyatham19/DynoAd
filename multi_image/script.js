const dropArea = document.getElementById("drop-area")

dropArea.addEventListener("dragover",(e)=>{
e.preventDefault()
dropArea.style.borderColor="#9333ea"
})

dropArea.addEventListener("dragleave",()=>{
dropArea.style.borderColor="rgba(255,255,255,.2)"
})