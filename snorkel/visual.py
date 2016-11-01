from .models import Phrase
import subprocess
import os
import cv2
import numpy as np
import pandas as pd
from timeit import default_timer as timer
from pprint import pprint
from bs4 import BeautifulSoup
from collections import OrderedDict, defaultdict
from editdistance import eval as editdist

class VisualLinker():
    def __init__(self, pdf_path, session):
        self.session            = session
        self.pdf_path           = pdf_path
        self.pdf_file           = None
        self.document           = None
        self.coordinate_map     = None
        self.pdf_word_list      = None
        self.html_word_list     = None
        self.links              = None

    def visual_parse_and_link(self, document):
        DEBUG = False
        TIME = True
        self.document = document
        self.pdf_file = self.pdf_path + self.document.name + '.pdf'
        if DEBUG: print self.pdf_file
        
        tic = timer()
        self.extract_pdf_words()
        if DEBUG: pprint(self.pdf_word_list[:5])
        if DEBUG: pprint(self.coordinate_map.items()[:5])
        if TIME:  print "Elapsed: %0.3f s" % (timer() - tic)
        
        tic = timer()
        self.extract_html_words()
        if DEBUG: pprint(self.html_word_list[:5])
        if TIME:  print "Elapsed: %0.3f s" % (timer() - tic)
        
        # TEMP
        print len(self.pdf_word_list)
        self.pdf_word_list = [x for x in self.pdf_word_list if x[1]]
        print len(self.pdf_word_list)
        html_words = [x[1] for x in self.html_word_list]
        pdf_words  = [x[1] for x in self.pdf_word_list]
        html_only = set(html_words) - set(pdf_words)
        pdf_only = set(pdf_words) - set(html_words)
        print (len(html_only), len(pdf_only))
        # pprint(list(html_only))
        # pprint(list(pdf_only))
        pprint(zip(sorted(list(html_only)) + ([None] * (len(pdf_only)-len(html_only))), sorted(list(pdf_only))))
        # pprint(zip([word[1] for word in self.html_word_list], [None]*5 + [word[1] for word in self.pdf_word_list]))
        import pdb; pdb.set_trace()
        # TEMP

        tic = timer()
        self.link_better(search_max=200)
        if DEBUG: vizlink.display_links()
        if TIME:  print "Elapsed: %0.3f s" % (timer() - tic)
                    
        tic = timer()
        self.update_coordinates()
        if TIME:  print "Elapsed: %0.3f s" % (timer() - tic)

    def extract_pdf_words(self):
        num_pages = subprocess.check_output(
            "pdfinfo {} | grep Pages  | sed 's/[^0-9]*//'".format(self.pdf_file), shell=True)
        pdf_word_list = []
        coordinate_map= {}
        for i in range(1, int(num_pages)+1):
            html_content = subprocess.check_output('pdftotext -f {} -l {} -bbox-layout {} -'.format(str(i), str(i), self.pdf_file), shell=True)
            pdf_word_list_i, coordinate_map_i = self._coordinates_from_HTML(html_content, i)
            # TODO: this is a hack for testing; use a more permanent solution for tokenizing
            # NOTE: re.split("([\(\)\,\'])", string)
            pdf_word_list_additions = []
            for j, (word_id, word) in enumerate(pdf_word_list_i):
                if len(word) >= 2 and not word[-1].isalnum():
                    pdf_word_list_i[j] = (word_id, word[:-1])
                    page, idx = word_id
                    new_word_id = (page, idx + 0.5)
                    pdf_word_list_additions.append((new_word_id, word[-1]))
                    coordinate_map_i[new_word_id] = coordinate_map_i[word_id]
            pdf_word_list_i += pdf_word_list_additions
            # sort pdf_word_list by page, then top, then left
            pdf_word_list += sorted(pdf_word_list_i, key=lambda (word_id,_): coordinate_map_i[word_id][0:3])
            coordinate_map.update(coordinate_map_i)
        self.pdf_word_list = pdf_word_list
        self.coordinate_map = coordinate_map
        print "Extracted %d pdf words" % len(self.pdf_word_list)

    def _coordinates_from_HTML(self, html_content, page_num):
        pdf_word_list = []
        coordinate_map = {}
        soup = BeautifulSoup(html_content, "html.parser")
        lines = soup.find_all('line')
        i = 0  # counter for word_id in page_num
        for line in lines:
            j = 0  # counter for words within a line (words that are not whitespaces)
            words = line.find_all("word")
            y_min_line = int(float(words[0].get('ymin')))
            y_max_line = 0
            for word in words:
                xmin = int(float(word.get('xmin')))
                xmax = int(float(word.get('xmax')))
                ymin = int(float(word.get('ymin')))
                ymax = int(float(word.get('ymax')))
                content = word.getText()
                if len(content) > 0:  # Ignore white spaces
                    if ymin < y_min_line:
                        y_min_line = ymin
                    if ymax > y_max_line:
                        y_max_line = ymax
                    word_id = (page_num, i)
                    pdf_word_list.append((word_id, content))
                    coordinate_map[word_id] = (page_num, xmin, xmax)  # TODO: check this order
                    i += 1
                    j +=1
            for word_id, _ in pdf_word_list[-j:]:
                page_num, xmin, xmax = coordinate_map[word_id]
                coordinate_map[word_id] = (page_num, y_min_line, xmin, y_max_line, xmax)
        return pdf_word_list, coordinate_map

    def extract_html_words(self):
        html_word_list = []
        for phrase in self.document.phrases:
            for i, word in enumerate(phrase.words):
                html_word_list.append(((phrase.id, i), word))
        self.html_word_list = html_word_list
        print "Extracted %d html words" % len(self.html_word_list)

    def link_better(self, search_max=200):
        # NOTE: there are probably some inefficiencies here from rehashing words 
        # multiple times, but we're not going to worry about that for now
        def link_matches(l, u, offset):
            print (l, u), (l*word_ratio, u*word_ratio)
            html_dict = defaultdict(list)
            pdf_dict = defaultdict(list)
            for i, (uid, word) in enumerate(self.html_word_list[l:u]):
                html_dict[word].append((uid, i))
            for j, (uid, word) in enumerate(self.pdf_word_list[offset+l:offset+u]):
                pdf_dict[word].append((uid, j))
                for word, html_list in html_dict.items():
                    if len(html_list) == len(pdf_dict[word]):
                        pdf_list = pdf_dict[word]
                        for j, (uid, i) in enumerate(html_list):
                            self.links[i] = pdf_list[j][0]
        
        N = len(self.html_word_list)
        self.links = [None] * N
        search_radius = search_max/2
        word_ratio = float(len(self.pdf_word_list))/len(self.html_word_list)

        # first pass: global
        link_matches(0, N, 0)
        # ~50% of links are anchored in bc546-d
        
        # second pass: local
        for i in range(N/search_radius + 1):
            offset = 0
            link_matches(max(0, i*search_radius - search_radius), min(N, i*search_radius + search_radius), offset)

        # third pass: edit distance matches


        
        # for link in links:
        #     if link is None:

        import pdb; pdb.set_trace()

        # convert list to dict
        self.links = OrderedDict((self.html_word_list[i][0], self.links[i]) for i in range(N))


    def link_lists(self, search_max=200, editCost=20, offsetCost=1, offsetInertia=5):
        DEBUG = True
        if DEBUG:
            offsetHist = []
            jHist = []
            editDistHist = 0
        offset = self._calculate_offset(self.html_word_list, self.pdf_word_list, max(search_max/10,5), search_max)
        offsets = [offset] * offsetInertia
        searchOrder = np.array([(-1)**(i%2) * (i/2) for i in range(1, search_max+1)])
        links = OrderedDict()
        for i, a in enumerate(self.html_word_list):
            j = 0
            searchIndices = np.clip(offset + searchOrder, 0, len(self.pdf_word_list)-1)
            jMax = len(searchIndices)
            matched = False
            # Search first for exact matches
            while not matched and j < jMax:
                b = self.pdf_word_list[searchIndices[j]]
                if a[1] == b[1]:
                    links[a[0]] = b[0]
                    matched = True
                    offsets[i % offsetInertia] = searchIndices[j]  + 1
                    offset = int(np.median(offsets))
                    if DEBUG:
                        jHist.append(j)
                        offsetHist.append(offset)
                j += 1
            # If necessary, search for min edit distance
            if not matched:
                cost = [0] * search_max
                for k, m in enumerate(searchIndices):
                    cost[k] = (editdist(a[1],self.pdf_word_list[m][1]) * editCost +
                            k * offsetCost)
                nearest = np.argmin(cost)            
                links[a[0]] = self.pdf_word_list[searchIndices[nearest]][0]
                if DEBUG:
                    jHist.append(nearest)
                    offsetHist.append(searchIndices[nearest])
                    editDistHist += 1
        if DEBUG:
            # print offsetHist
            # print jHist
            # print editDistHist
            self.offsetHist = offsetHist
        self.links = links
        print "Linked %d words to %d bounding boxes" % (len(self.html_word_list), len(self.pdf_word_list))

    def _calculate_offset(self, listA, listB, seedSize, maxOffset):
        wordsA = zip(*listA[:seedSize])[1]
        wordsB = zip(*listB[:maxOffset])[1]
        offsets = []
        for i in range(seedSize):
            try:
                offsets.append(wordsB.index(wordsA[i]) - i)
            except:
                pass
        return int(np.median(offsets))

    def display_links(self, max_rows=100):
        html = []
        pdf = []
        j = []
        for i, l in enumerate(self.links):
            html.append(self.html_word_list[i][1])
            for k, b in enumerate(self.pdf_word_list):
                if b[0] == self.links[self.html_word_list[i][0]]:
                    pdf.append(b[1])
                    j.append(k)
                    break
        assert(len(pdf) == len(html))

        data = {
            'i': range(len(self.links)),
            'html': html,
            'pdf': pdf,
            'j': j,
            'offset': self.offsetHist
        }
        pd.set_option('display.max_rows', max_rows);
        return pd.DataFrame(data, columns=['i','html','pdf','j','offset'])
        # pd.reset_option('display.max_rows');

    def update_coordinates(self):
        for phrase in self.document.phrases:
            (page, top, left, bottom, right) = zip(
                *[self.coordinate_map[self.links[((phrase.id), i)]] for i in range(len(phrase.words))])
            page = page[0]
            self.session.query(Phrase).filter(Phrase.id == phrase.id).update(
                {"page": page, 
                "top":  list(top), 
                "left": list(left), 
                "bottom": list(bottom), 
                "right": list(right)})
        self.session.commit()
        print "Updated coordinates in snorkel.db"

    def display_candidates(self, candidates, page_num=1, display=True):
        """
        Displays the bounding boxes corresponding to candidates on an image of the pdf
        # boxes is a list of 5-tuples (page, top, left, bottom, right)
        """
        boxes = [get_box(span) for c in candidates for span in c.get_arguments()]
        self.display_boxes(boxes, page_num=page_num, display=display, alternate_colors=True)

    def display_boxes(self, boxes, page_num=1, display=True, alternate_colors=False):
        """
        Displays each of the bounding boxes passed in 'boxes' on an image of the pdf
        pointed to by pdf_file
        # boxes is a list of 5-tuples (page, top, left, bottom, right)
        """
        if display:
            (img, img_path) = pdf_to_img(self.pdf_file, page_num)
            colors = [(255,0,0), (0,0,255)]
        boxes_per_page = defaultdict(int)
        boxes_by_page = defaultdict(list)
        for i, (page, top, left, bottom, right) in enumerate(boxes):
            boxes_per_page[page] += 1 
            if (top, left, bottom, right) not in boxes_by_page[page]:
                boxes_by_page[page].append((top, left, bottom, right))
                if page == page_num and display:
                    color = colors[i % 2] if alternate_colors else colors[0]
                    cv2.rectangle(img, (left, top), (right, bottom), color, 1)
        print "Boxes per page: total (unique)"
        for (page, count) in sorted(boxes_per_page.items()):
            print "Page %d: %d (%d)" % (page, count, len(boxes_by_page[page]))
        if display:
            cv2.imshow('Bounding boxes', img)
            cv2.waitKey() # press any key to exit the opencv output 
            cv2.destroyAllWindows() 
            os.system('rm {}'.format(img_path)) # delete image

    def display_word(self, target, page_num=1):
        boxes = []
        for phrase in self.document.phrases:
            for i, word in enumerate(phrase.words):
                if word == target:
                    boxes.append((
                        phrase.page,
                        phrase.top[i], 
                        phrase.left[i],
                        phrase.bottom[i],
                        phrase.right[i]))
        self.display_boxes(boxes, page_num)
                

def pdf_to_img(pdf_file, page_num, page_width=612, page_height=792):
    basename = subprocess.check_output('basename {} .pdf'.format(pdf_file), shell=True)
    dirname = subprocess.check_output('dirname {}'.format(pdf_file), shell=True)
    img_path = dirname.rstrip() + '/' + basename.rstrip()
    os.system('pdftoppm -f {} -l {} -jpeg {} {}'.format(page_num, page_num, pdf_file, img_path))
    img_path += '-{}.jpg'.format(page_num)
    img = cv2.resize(cv2.imread(img_path), (page_width, page_height))
    return (img, img_path)

def get_box(span):
    return (span.parent.page, 
            min(span.get_attrib_tokens('top')),
            max(span.get_attrib_tokens('left')),
            min(span.get_attrib_tokens('bottom')),
            max(span.get_attrib_tokens('right')))



