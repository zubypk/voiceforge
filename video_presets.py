"""Ready-made video projects (size + theme + scenes) in English and Arabic."""
from __future__ import annotations


def _s(layout, title, body, narration, **extra):
    return {"layout": layout, "title": title, "body": body, "narration": narration, **extra}


PRESETS = {
    "lesson": {
        "label": {"en": "Educational lesson", "ar": "درس تعليمي"},
        "desc": {"en": "Title, objectives, concept, example, summary. YouTube 16:9.",
                 "ar": "عنوان، أهداف، مفهوم، مثال، ملخص. يوتيوب 16:9."},
        "size": "youtube-1080", "theme": "academy",
        "scenes": {
            "en": [
                _s("title", "Lesson title", "A clear, friendly introduction", "Welcome! In this lesson we will learn the key ideas step by step."),
                _s("bullets", "What you will learn", "The main idea\nA simple example\nHow to practice", "By the end of this lesson you will understand the main idea, see a simple example, and know how to practice."),
                _s("text", "Key concept", "Explain the most important idea in one or two clear sentences.", "Here is the key concept. Explain it in simple words, then give a short example."),
                _s("bullets", "Example", "Show the idea in action\nName each step\nCheck the result", "Let us look at an example. First we show the idea in action, then we name each step, and finally we check the result."),
                _s("bullets", "Summary", "Idea one\nIdea two\nIdea three", "To summarize, remember these three ideas. Practice them and you will improve quickly."),
                _s("title", "Thank you", "See you in the next lesson", "Thank you for watching. See you in the next lesson!"),
            ],
            "ar": [
                _s("title", "عنوان الدرس", "مقدمة واضحة وبسيطة", "أهلاً بكم! في هذا الدرس سنتعرف على الأفكار الأساسية خطوة بخطوة."),
                _s("bullets", "ماذا ستتعلم", "الفكرة الرئيسية\nمثال بسيط\nكيف تتدرب", "في نهاية هذا الدرس ستفهم الفكرة الرئيسية، وسترى مثالاً بسيطاً، وتعرف كيف تتدرب."),
                _s("text", "المفهوم الأساسي", "اشرح أهم فكرة في جملة أو جملتين واضحتين.", "هذا هو المفهوم الأساسي. اشرحه بكلمات بسيطة، ثم قدّم مثالاً قصيراً."),
                _s("bullets", "مثال", "نعرض الفكرة عملياً\nنسمّي كل خطوة\nنتحقق من النتيجة", "لننظر إلى مثال. أولاً نعرض الفكرة عملياً، ثم نسمّي كل خطوة، وأخيراً نتحقق من النتيجة."),
                _s("bullets", "الملخص", "الفكرة الأولى\nالفكرة الثانية\nالفكرة الثالثة", "وللتلخيص، تذكّر هذه الأفكار الثلاث. تدرّب عليها وستتحسن بسرعة."),
                _s("title", "شكراً لك", "نراك في الدرس القادم", "شكراً لمتابعتك. نراكم في الدرس القادم!"),
            ],
        },
    },
    "explainer": {
        "label": {"en": "YouTube explainer", "ar": "فيديو شرح لليوتيوب"},
        "desc": {"en": "Hook, problem, three points, call to action. 16:9.",
                 "ar": "جملة جذب، مشكلة، ثلاث نقاط، دعوة لاتخاذ إجراء. 16:9."},
        "size": "youtube-1080", "theme": "midnight",
        "scenes": {
            "en": [
                _s("title", "Did you know?", "One idea that changes everything", "Did you know there is one simple idea that changes everything? Stay with me."),
                _s("text", "The problem", "Most people struggle with this because nobody explains it simply.", "Most people struggle with this topic because nobody explains it in a simple way."),
                _s("bullets", "Three key points", "Point one\nPoint two\nPoint three", "Here are three key points. First, point one. Second, point two. Third, point three."),
                _s("quote", "Remember", "Small steps every day beat big steps once.", "Remember: small steps every day beat big steps once."),
                _s("title", "Like & subscribe", "New videos every week", "If this helped, like the video and subscribe for new videos every week."),
            ],
            "ar": [
                _s("title", "هل تعلم؟", "فكرة واحدة تغيّر كل شيء", "هل تعلم أن هناك فكرة بسيطة واحدة تغيّر كل شيء؟ ابقَ معي."),
                _s("text", "المشكلة", "يواجه معظم الناس صعوبة في هذا الموضوع لأن لا أحد يشرحه ببساطة.", "يواجه معظم الناس صعوبة في هذا الموضوع لأن لا أحد يشرحه بطريقة بسيطة."),
                _s("bullets", "ثلاث نقاط أساسية", "النقطة الأولى\nالنقطة الثانية\nالنقطة الثالثة", "إليك ثلاث نقاط أساسية. أولاً، النقطة الأولى. ثانياً، النقطة الثانية. ثالثاً، النقطة الثالثة."),
                _s("quote", "تذكّر", "خطوات صغيرة كل يوم أفضل من خطوة كبيرة مرة واحدة.", "تذكّر: خطوات صغيرة كل يوم أفضل من خطوة كبيرة مرة واحدة."),
                _s("title", "اشترك وفعّل الجرس", "فيديوهات جديدة كل أسبوع", "إن أفادك هذا الفيديو فاضغط إعجاب واشترك لتصلك فيديوهات جديدة كل أسبوع."),
            ],
        },
    },
    "short": {
        "label": {"en": "Short · Reel · TikTok", "ar": "فيديو قصير · ريلز · تيك توك"},
        "desc": {"en": "Fast hook, three tips, follow. Vertical 9:16.",
                 "ar": "جملة جذب سريعة، ثلاث نصائح، متابعة. عمودي 9:16."},
        "size": "shorts", "theme": "bold",
        "scenes": {
            "en": [
                _s("title", "3 tips you need", "Watch until the end", "Three quick tips you need to know. Watch until the end."),
                _s("text", "Tip 1", "Start small and stay consistent.", "Tip one. Start small and stay consistent."),
                _s("text", "Tip 2", "Practice a little every day.", "Tip two. Practice a little every day."),
                _s("text", "Tip 3", "Review what you learned each week.", "Tip three. Review what you learned each week."),
                _s("title", "Follow for more", "New tips every day", "Follow for more tips every day."),
            ],
            "ar": [
                _s("title", "٣ نصائح تحتاجها", "شاهد حتى النهاية", "ثلاث نصائح سريعة تحتاج إلى معرفتها. شاهد حتى النهاية."),
                _s("text", "النصيحة ١", "ابدأ بخطوات صغيرة وحافظ على الاستمرار.", "النصيحة الأولى. ابدأ بخطوات صغيرة وحافظ على الاستمرار."),
                _s("text", "النصيحة ٢", "تدرّب قليلاً كل يوم.", "النصيحة الثانية. تدرّب قليلاً كل يوم."),
                _s("text", "النصيحة ٣", "راجع ما تعلمته كل أسبوع.", "النصيحة الثالثة. راجع ما تعلمته كل أسبوع."),
                _s("title", "تابعنا للمزيد", "نصائح جديدة كل يوم", "تابعنا لتصلك نصائح جديدة كل يوم."),
            ],
        },
    },
    "course": {
        "label": {"en": "Course intro · Presentation", "ar": "مقدمة دورة · عرض تقديمي"},
        "desc": {"en": "Welcome, agenda, instructor, next steps. Classroom 4:3.",
                 "ar": "ترحيب، جدول، المدرّب، الخطوات التالية. فصل دراسي 4:3."},
        "size": "classroom", "theme": "clean",
        "scenes": {
            "en": [
                _s("title", "Course name", "Welcome to the course", "Welcome to the course. I am glad you are here."),
                _s("bullets", "Agenda", "Module one: basics\nModule two: practice\nModule three: final project", "Here is our agenda. We start with the basics, then practice, and finish with a final project."),
                _s("text", "Your instructor", "Add a short introduction about yourself and your experience.", "A few words about me and my experience, so you know what to expect."),
                _s("bullets", "Next steps", "Watch lesson one\nDo the exercise\nAsk your questions", "To get started, watch lesson one, do the exercise, and ask your questions."),
            ],
            "ar": [
                _s("title", "اسم الدورة", "مرحباً بكم في الدورة", "مرحباً بكم في الدورة. يسعدني وجودكم معنا."),
                _s("bullets", "جدول الدورة", "الوحدة الأولى: الأساسيات\nالوحدة الثانية: التطبيق\nالوحدة الثالثة: المشروع النهائي", "هذا هو جدول الدورة. نبدأ بالأساسيات، ثم التطبيق، وننتهي بمشروع نهائي."),
                _s("text", "المدرّب", "أضف نبذة قصيرة عن نفسك وعن خبرتك.", "كلمات قليلة عني وعن خبرتي لتعرفوا ماذا تتوقعون."),
                _s("bullets", "الخطوات التالية", "شاهد الدرس الأول\nحلّ التمرين\nاطرح أسئلتك", "للبدء، شاهد الدرس الأول، وحلّ التمرين، واطرح أسئلتك."),
            ],
        },
    },
    "quiz": {
        "label": {"en": "Quiz · Recap", "ar": "اختبار · مراجعة"},
        "desc": {"en": "Question, options, answer. Square 1:1 for social feeds.",
                 "ar": "سؤال، خيارات، إجابة. مربّع 1:1 للشبكات الاجتماعية."},
        "size": "square", "theme": "chalkboard",
        "scenes": {
            "en": [
                _s("title", "Quick quiz", "Can you answer this?", "Time for a quick quiz. Can you answer this?"),
                _s("bullets", "Which one is correct?", "Option A\nOption B\nOption C", "Which one is correct? Option A, option B, or option C?"),
                _s("title", "The answer", "Option B", "The correct answer is option B. Did you get it right?"),
            ],
            "ar": [
                _s("title", "اختبار سريع", "هل تستطيع الإجابة؟", "حان وقت اختبار سريع. هل تستطيع الإجابة؟"),
                _s("bullets", "أيّها الصحيح؟", "الخيار أ\nالخيار ب\nالخيار ج", "أيّها الصحيح؟ الخيار أ، أم الخيار ب، أم الخيار ج؟"),
                _s("title", "الإجابة", "الخيار ب", "الإجابة الصحيحة هي الخيار ب. هل أجبت بشكل صحيح؟"),
            ],
        },
    },
}
