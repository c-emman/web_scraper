from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from web_scraper.config import AnyEc, Configuration_XPATH, Db_Config
from web_scraper.scraper import Scraper
import pandas as pd
import argparse
import sqlalchemy
import boto3
import uuid
import os
import json
import urllib.request
import psycopg2

class Item_Scraper(Scraper):

    def __init__(self, *args, **kwargs) -> False:

        super().__init__(*args, **kwargs)
        self.link_list = list()
        self.department = str()
        self.category = str()
        self.subcategory = str()
        self.list_max = 3
        self.s3_client = boto3.client('s3')
        self.bucketname = 'chris-aircore-s3bucket'
        self.engine = sqlalchemy.create_engine(f'{Db_Config.DATABASE_TYPE}+{Db_Config.DBAPI}://{Db_Config.USER}:{Db_Config.PASSWORD}@{Db_Config.ENDPOINT}:{Db_Config.PORT}/{Db_Config.DATABASE}')
        # self.conn = self.engine.connect()
        self.parser = argparse.ArgumentParser(description='Item Scraper class which will scrape products from website.')
        self.parser.add_argument( "-m", "--men", help='Scrape only the Mens department.', default=False, action='store_true')
        self.parser.add_argument("-w", "--women", help='Scrape only the Womens department.', default=False, action='store_true')
        self.parser.add_argument("-k", "--kids", help='Scrape only the Kids department.', default=False, action='store_true')
        self.parser.add_argument("-l", "--locally", help='Save scraped data on local machine only.', default=False, action='store_true')
        self.parser.add_argument("-c", "--cloud", help='Upload data to S3 and AWS RDS only.', default=False, action='store_true')
        self.args = self.parser.parse_args()
        self.dep_list = Configuration_XPATH.DEP_LIST
        if self.args.men is True:
            self.dep_list = Configuration_XPATH.DEP_LIST[0]
            print('Will scrape only the Mens department.')
        elif self.args.women is True:
            self.dep_list = Configuration_XPATH.DEP_LIST[1]
            print('Will scrape only the Womens department.')
        elif self.args.kids is True:
            self.dep_list = Configuration_XPATH.DEP_LIST[2]
            print('Will scrape only the Kids department.')
        else:
            print('Will scrape Mens, Womens and Kids departments.')
        
        if self.args.cloud is True:
            print('Documents will not save locally; will save to AWS S3 and RDS only.')
        elif self.args.locally is True:
            print('Documents will save locally only.')
        else:
            print('Documents will be saved both locally and on AWS cloud.')

    def run_full_scrape(self) -> None:
        """
        This function runs the full scrape of the website of interest.

        Return:
            None
        """
        self.load_and_accept_cookies(Configuration_XPATH.WEBSITE)
        self.load_and_reject_promotion()    
        
        if type(self.dep_list) == list:
            for department in self.dep_list:
                self.department = department
                if self.args.locally is False:
                    self.engine.execute(f'''CREATE SCHEMA IF NOT EXISTS {self.department}_data''')
                    print(f'The {self.department}_data schema has been made')
                category_dict_list = self.get_categories(self.department)
                full_scrape_list = self.get_subcategories_links(category_dict_list) 
                self.run_subcategory_scrape(full_scrape_list)
                print(f"{self.department} department has been scraped")
        else:
            self.department = self.dep_list
            if self.args.locally is False:
                self.engine.execute(f'''CREATE SCHEMA IF NOT EXISTS {self.department}_data''')
            category_dict_list = self.get_categories(self.department)
            full_scrape_list = self.get_subcategories_links(category_dict_list) 
            self.run_subcategory_scrape(full_scrape_list)
            print(f"{self.department} department has been scraped")
    
    def run_subcategory_scrape(self, full_scrape_list) -> None:
        """
        This function runs a full scrape of a particular subcategory on the website of interest

        Args:
            full_scrape_list (list): A list of dicts containing each sub-category name, link and the corresponding category and department data

        Return:
            None
        """
        for full_scrape_dict in full_scrape_list:
            subcategory_link = full_scrape_dict["subcategory_link"]
            self.category = full_scrape_dict["category"]
            self.subcategory = full_scrape_dict["subcategory"]
            self.driver.get(subcategory_link)
            index = int(len(Configuration_XPATH.WEBSITE)) + int(len(self.department)) + int(len(self.category)) + int(len(self.subcategory)) + 10
            self.link_list = self.get_links(index)
            self.max_items = min(self.list_max, len(self.link_list))
            if self.args.locally is False:
                self.engine.execute(f'''CREATE TABLE IF NOT EXISTS {self.department}_data.{self.subcategory} (
                                            uuid VARCHAR(36) PRIMARY KEY,
                                            product_no VARCHAR(8) NOT NULL,
                                            brand VARCHAR(30), 
                                            product_info VARCHAR(100),
                                            price FLOAT NOT NULL,
                                            size_and_fit VARCHAR(1000),
                                            brand_bio VARCHAR(1000)
                                            );''')
            self.run_item_scrape()
            print(f"{self.subcategory} links in the {self.department}'s department have been retrieved")

    def run_item_scrape(self) -> None:
        """
        This function runs an scrape on a list of items provided. 

        Return:
            None
        """
        for link in self.link_list[:self.max_items]:
            self.driver.get(link)
            path = Configuration_XPATH.RAW_DATA_PATH + f'/{self.department}/{self.category}/{self.subcategory}'
            self.create_dir(path)
            product_dict = self.scrape_item_data()
            value_1 = f"'{product_dict['uuid']}'"
            value_2 = f"'{product_dict['product_no']}'"
            value_3 = f"'{product_dict['brand']}'"
            transform_4 = product_dict['product_info'].replace("'s", "s").replace("'", ".")
            value_4 = f"'{transform_4}'"
            value_5 = float(product_dict['price'][1:].replace(",", ""))
            if 'size_and_fit' in product_dict:
                transform_6 = product_dict['size_and_fit'].replace("'s", "s").replace("'", ".")
                value_6 = f"'{transform_6}'"
            else:
                value_6 = "''"
            if 'brand_bio' in product_dict:
                transform_7 = product_dict['brand_bio'].replace("'s", "s").replace("'", ".")
                value_7 = f"'{transform_7}'"
            else:
                value_7 = "''"
            table_insert = f'({value_1}, {value_2}, {value_3}, {value_4}, {value_5}, {value_6}, {value_7})'
            item_path = path + f'/{product_dict["product_no"]}'
            self.create_dir(item_path)
            path_img = item_path + '/images'
            self.create_dir(path_img)
            images_list = self.get_images(path_img, product_dict)
            product_dict["image_links"] = images_list
            # need to find solution to giving option to save locally or on cloud for json file.encode('utf8')
            if self.args.cloud is True:
                self.s3_client.put_object(Body=json.dumps(product_dict), Bucket=self.bucketname, Key=f'{product_dict["product_no"]}.json')
            if self.args.cloud is False:
                self.create_json(product_dict, item_path)
            if self.args.locally is False and self.args.cloud is False:
                self.upload_data_s3(f'{item_path}/data.json', self.bucketname, f'{product_dict["product_no"]}.json')
            if self.args.locally is False:
                self.engine.execute(sqlalchemy.text(f'''INSERT INTO {self.department}_data.{self.subcategory}(uuid, product_no, brand, product_info, price, size_and_fit, brand_bio) VALUES{table_insert}'''))   
        print(f"All the {self.subcategory} data in the {self.department}'s department has been scraped.")
        

    def scrape_item_data(self) -> dict:
        """
        This function scrapes the data for an individual item into a dict and saves that dict as a json file

        Args:
            link_list (list): A list of links to all the items within a subcategory
            department (str): The department which is being scraped
            category (str): The category the item is located in
            sub_category (str): The sub-category the item is located in

        Returns:
            dict
        """
        product_dict = dict()
        WebDriverWait(self.driver, self.delay).until(EC.presence_of_all_elements_located((By.XPATH, Configuration_XPATH.product_no_xpath)))
        product_dict["uuid"] = str(uuid.uuid4())
        product_dict["product_no"] = self.driver.find_elements(By.XPATH, Configuration_XPATH.product_no_xpath)[0].text     
        product_dict["brand"] = self.driver.find_element(By.XPATH, Configuration_XPATH.brand_xpath).text
        product_dict["product_info"] = self.driver.find_element(By.XPATH, Configuration_XPATH.product_info_xpath).text
        product_dict["price"] = WebDriverWait(self.driver, self.delay).until(AnyEc(EC.presence_of_element_located((By.XPATH,Configuration_XPATH.price_xpath)), EC.presence_of_element_located((By.XPATH, Configuration_XPATH.price_sale_xpath)))).text
        self.driver.execute_script("window.scrollTo(0, 500);")
        if self.driver.find_element(By.XPATH, Configuration_XPATH.HEADING_INFO_ACTIVE_XPATH).text.lower() == "size & fit":
            product_dict["size_and_fit"] = self.driver.find_element(By.XPATH, Configuration_XPATH.size_and_fit_xpath).text    
        else:
            try:
                WebDriverWait(self.driver, self.delay).until(EC.presence_of_element_located((By.XPATH, Configuration_XPATH.SIZE_AND_FIT_INACTIVE_XPATH)))
                size_and_fit_button = self.driver.find_element(By.XPATH, Configuration_XPATH.SIZE_AND_FIT_INACTIVE_XPATH)
                size_and_fit_button.click()
                product_dict["size_and_fit"] = self.driver.find_element(By.XPATH, Configuration_XPATH.size_and_fit_xpath).text
            except:
                pass
        
        if self.driver.find_element(By.XPATH, Configuration_XPATH.HEADING_INFO_ACTIVE_XPATH).text.lower() == "brand bio":
            product_dict["brand_bio"] = self.driver.find_element(By.XPATH, Configuration_XPATH.brand_bio_xpath).text   
        else:
            try:
                WebDriverWait(self.driver, self.delay).until(EC.presence_of_element_located((By.XPATH, Configuration_XPATH.BRAND_BIO_INACTIVE_XPATH)))
                brand_bio_button =  self.driver.find_element(By.XPATH, Configuration_XPATH.BRAND_BIO_INACTIVE_XPATH)
                brand_bio_button.click()
                product_dict["brand_bio"] = self.driver.find_element(By.XPATH, Configuration_XPATH.brand_bio_xpath).text
            except:
                pass

        return product_dict
      
    def get_images(self, path_img: str, product_dict: dict) -> list:
        """
        The function will get all the images for an item and call a function to download the image

        Args:
            path_img (str): The PATH for the /images directory within the specified item directory
            product_dict (dict): Dictionary of the data for a specfic item.

        Returns:
            images_list (list): A list of the image links for a specific item.
        """
        images_list = []
        images_xpath = self.driver.find_elements(By.XPATH, Configuration_XPATH.images_xpath)

        a = 1
        for image in images_xpath:
            image_dict = dict()
            image_dict["image_no"] = str(f'{product_dict["product_no"]}_{a}')
            image_dict["link"] = image.get_attribute('src')
            img_name = path_img + str(f'/{product_dict["product_no"]}_{a}')
            images_list.append(image_dict)
            if self.args.cloud is False:
                self.download_images(image_dict["link"], img_name)
                if self.args.locally is False:
                    self.upload_data_s3(f'{img_name}.jpg', self.bucketname, f'{image_dict["image_no"]}.jpg')
            else:
                #add uploading image directly to s3
                pass
            a+=1
        
        return images_list

    def create_dir(self, PATH: str) -> None:
        """
        This function will create a directory which does not exist

        Args:
            PATH (str): The desired PATH to create the directory

        Return:
            None
        """
        if self.args.cloud is False:
            if os.path.exists(PATH) == False:
                os.makedirs(PATH)

    def create_json(self, product_dict: dict, item_path: str) -> None:
        """
        The function will create a JSON file for a dictionary in a desired PATH

        Args:
            product_dict (dict): Dictionary of the data for a specfic item
            item_path (str): The PATH where the data for a specified item will be located

        Returns:
            None
        """
        with open(f'{item_path}/data.json', 'w') as fp:
            json.dump(product_dict, fp)

    def download_images(self, image_link: str, img_name: str) -> None:
        """
        This function downloads an image from a URL

        Args:
            image_link (str): The link to the image to be downloaded
            img_name (str): The reference name for the image

        Returns:
            None
        """
        path  = img_name + '.jpg'
        urllib.request.urlretrieve(image_link, path)

    def upload_data_s3(self, filename, bucketname, object_name):
        self.s3_client.upload_file(filename, bucketname, object_name)
    
    def locally_or_cloud(self,  operation):
        if self.args.locally is False:
            operation
        else:
            pass